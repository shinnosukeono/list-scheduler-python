## 実行方法

命令列はテキストファイルで表現する。対応している命令および書式は

- `add c a b`
- `mul c a b`
- `fadd c a b`
- `fmul c a b`
- `lw a b imm`
- `sw a b imm`

である。2項演算子 (`add`, `mul`, `fadd`, `fmul`) は レジスタ `a` と `b` の演算結果を レジスタ `c` に格納する。`lw` はレジスタ `b` の値に即値 `imm` を足したアドレスから値を読み取り、レジスタ `a` に格納する。`sw` はレジスタ `a` の値を同様の計算方法で計算したアドレスに格納する。レジスタの表現形式は何でもよい。

スケジューリングの実行は、

```
python list_scheduling.py sample.txt {time|resource}
```

のように行う。第1引数 `sample.txt` は命令列のファイル名である。第2引数はスケジューリングの戦略を指定するもので、`time` または `resource` が選べる。これらの戦略の詳細は後述する。

このプログラムを実行すると、スケジューリング結果が以下のように出力される。

```
1: lw a1 sp -32: -14
2: lw a2 a1 0: -12
3: lw a3 sp -32: -14
4: lw a4 a3 4: -12
5: fadd a5 a2 a4: -10
6: lw a6 sp -24: -9
7: lw a7 a6 8: -7
8: fadd a8 a5 a7: -5
time: 0
        1: lw a1 sp -32
time: 2
        3: lw a3 sp -32
time: 4
        4: lw a4 a3 4
time: 6
        2: lw a2 a1 0
time: 8
        5: fadd a5 a2 a4
        6: lw a6 sp -24
time: 10
        7: lw a7 a6 8
time: 13
        8: fadd a8 a5 a7
```

始めの数行は、入力された各命令に対して先頭に行番号を、末尾に優先度を付加したものを出力している。優先度は値が小さいほど高い。残りの行は、命令が実行された時刻と命令の内容を出力している。

## 実装

### データ構造

プログラムは主に命令、演算ユニット、スケジューラをそれぞれ表現する3つのクラスによって構成される。

命令クラス `Instr` は一つの命令を表現する。メンバ変数に

- 自身の結果を必要とする命令リスト `next_list`
- 自身が依存する命令 `dependent_list`

を保持しており、これによって依存グラフを表現する。つまり入次数は `dependent_list` の長さであり、出次数は `next_list` の長さである。

すべての命令は、スケジューラクラス `Scheduler` の

- `instr_wait_list` : 実行待ちでまだready setに入っていない命令のリスト
- `ready_set` : 実行待ちで依存関係のない命令のリスト
- `instr_dispatched_list` : 実行が開始された命令のリスト

のいずれかのメンバに入る。初期状態では全ての命令が `instr_wait_list` に入っているが、各時刻において 現在の依存関係に基づく `ready_set` の構築と命令実行を繰り返し、最終的にすべての命令を `instr_dispatched_list` に入れることをスケジューリングの目標とする。

演算ユニットクラス `OpUnits` は、一つの種類の演算器群をまとめて表現する。メンバ変数に

- 演算器の個数 `n`
- 各演算器の状態（使用可能かどうか、最後に使用を開始した時刻はいつか）を保持するリスト `unit_list`

を保持しており、後述するいくつかの補助メソッドと組み合わせて演算器群の状態を管理する。`Scheduler` クラスの `alu, fpu, memory` メンバはそれぞれ `OpUnits` インスタンスであり、それぞれALU, FPU, Memoryを表現している。

### 依存グラフと優先度

依存グラフの構築（つまり各 `Instr` インスタンスの `next_list` および `dependent_list` の設定）はスケジューラが行う。スケジューラは各命令の右辺と左辺のレジスタを分析し、

- 注目している命令の右辺のレジスタが先行命令の左辺にあらわれていればRAW依存
- 注目している命令の左辺のレジスタが先行命令の左辺にあらわれていればWAW依存
- 注目している命令の右辺のレジスタが先行命令の右辺にあらわれていればWAR依存

という条件に基づいて依存関係を構築する。これは `Scheduler._set_dependency` メソッドが担当し、命令 `i` と先行命令 `j` について二重のループを回して上の条件をチェックしている。

```python
    def _set_dependency(self) -> None:
        """依存グラフを作る"""
        for i in range(len(self.instr_wait_list)):
            for j in range(0, i):
                for operand in self.instr_wait_list[i].right:
                    if operand in self.instr_wait_list[j].left:
                        # RAW依存
                        self.instr_wait_list[i].dependent_list.append(self.instr_wait_list[j])
                        self.instr_wait_list[j].next_list.append(self.instr_wait_list[i])
                for operand in self.instr_wait_list[i].left:
                    if operand in self.instr_wait_list[j].left:
                        # WAW依存
                        self.instr_wait_list[i].dependent_list.append(self.instr_wait_list[j])
                        self.instr_wait_list[j].next_list.append(self.instr_wait_list[i])
                    if operand in self.instr_wait_list[j].right:
                        # WAR依存
                        self.instr_wait_list[i].dependent_list.append(self.instr_wait_list[j])
                        self.instr_wait_list[j].next_list.append(self.instr_wait_list[i])
```

依存グラフが完成したら、次に優先度の設定を行う。これは `Scheduler._set_priority` メソッドが担当するが、実行時引数で指定した戦略に基づき、

- `_find_critical_path`: `time` が指定された場合に呼び出される。現在の命令から最後の命令までのクリティカルパスの符号を反転させたものを優先度とする。
- `_count_dependency`: `resource` が指定された場合に呼び出される。現在の命令の依存グラフ上での深さの符号を反転させたものを優先度とする。

のどちらかを呼び出す。ここで設定された優先度は、`Instr.priority` が保持する。

`_find_critical_path` 関数のクリティカルパスの探索には、Bellman-Ford法を用いている。Bellman-Ford法は単一始点最短経路探索に用いられるアルゴリズムであるので、辺の重みを先行命令の実行時間の符号を反転させたものとし、値が小さいほど実行時間が長いものとしてクリティカルパスの探索を最短経路探索に置き換えている。

`_count_dependency` にもBellman-Ford法を用いている。`_find_critial_path` は現在の命令から最後の命令に向かってクリティカルパスを計算するので、自身の結果を用いる命令のリストである `Instr.next_list` を辺として利用していたが、この関数は現在の命令が依存する命令に向かって（依存グラフを遡って）依存度を計算するので、`Instr.dependency_list` を辺として利用する（つまり辺の向きが逆になっている）。

### Ready Set

Ready setの構築は `Scheduler._update_ready_set` メソッドが担当する。依存グラフにおいて、依存命令が存在しないか、存在してもすべて実行が終了しているような命令は、ready setに入ることができる。私の実装では、実行が完了した命令を依存グラフから削除するのではなく、`Instr` インスタンスに実行状態を保持させることで表現している。

```python
    def _update_ready_set(self) -> None:
        """ready setを更新する"""
        ready_set = []
        for instr in self.instr_wait_list:
            flag = True  # 先行命令がすべて終了しているかを表すフラグ
            for dependent_instr in instr.dependent_list:
                if dependent_instr.get_status() != Status.DONE:
                    # 先行命令が一つでも終了していなければまだ実行できない
                    flag = False
                    break
            if flag:
                # 先行命令がすべて終了していればready setに追加
                # 依存する命令がない場合もここを通る
                hq.heappush(self.ready_set, instr)
                ready_set.append(instr)
```

`Instr.get_status()` メソッドは、命令の現在の実行状態を返す。依存命令に `Status.DONE` でないようなもの（つまりまだ実行が開始していないか、実行中であるもの）があれば、まだ命令をready setに入れることはできない。

また、ready setは優先度付きキューとして実装している（`hq` は優先度付きキューのライブラリ）。これは実行可能な命令の選択において、優先度の高いものから取り出せるようにするためである。

### 命令実行と制約の更新

命令の実行と制約の更新は `Scheduler._dispatch` メソッドが担当する。これは

1. ready setから優先度が高いものを取り出し、
2. 取り出した命令が使用する演算ユニットを `Scheduler._get_op_unit` によって取得し、
3. 演算ユニットがいっぱいであるかを `OpUnits.is_full` によって調べ、
4. いっぱいであれば1.に戻って次の命令を調べ、空きがあれば取り出した命令を実行対象に入れて1.に戻る

という手順で実行可能な命令をすべて選択する。実行の際は、

- `Instr` インスタンスに実行開始時刻を記録
- `OpUnits.allocate` メソッドで演算ユニットの状態を更新
- 実行命令を `Scheduler.ready_set` から `Scheduler.instr_dispatched_list` に移動

という操作を行う。`OpUnits.allocate` は割り当てた演算器の状態更新（時刻の記録など）だけでなく、次に割り当てる演算器番号のキャッシュも同時に行うが、これは以下のように行われる。

```python
        # 次に割り当てる演算器番号を更新
        if self.n_busy < self.n:
            for i in range(1, self.n):
                if not self.unit_list[(allocated + i) % self.n][1]:
                    self.next = (allocated + i) % self.n
                    break
```

常に演算器群の先頭から見るのではなく、割り当てた演算器（ `allocated` ）の次の演算器から見ることによって、状態を調べる演算器の個数を少なく抑える確率を上げている。

制約更新は、`Instr` クラスと `OpUnits` クラスの両方に実装されている `update` メソッドで行う。これは現在時刻と各インスタンスに記録されている実行開始時刻を比較し、実行終了時刻になったらインスタンスの状態を更新するものである。`Scheduler._update_ready_set` によるready setの更新も、毎時刻行われる。

### スケジューリング

以上で説明した関数を組み合わせて、スケジューリングを行う `Scheduler.schedule` メソッドは以下のように実装される。

```python
    def schedule(self) -> None:
        """全命令のスケジューリングを行う"""
        self._set_dependency()  # 依存グラフの初期化
        self._set_priority()  # 優先度の設定

        t = 0  # スケジュール開始
        self._update_ready_set()  # ready setを作成
        while len(self.instr_wait_list + self.ready_set) > 0:
            self._dispatch(t)  # 命令実行、制約の更新
            t += 1  # 時刻を進める
```

## 考察

### 動作確認

実行方法で記載した命令列（スライドの命令列を参考にした）は `sw` 命令が含まれていなかった。 `sw` を含む場合についてもテストする。以下のファイルを `sample2.txt` として用意する。

```
lw a1 sp -32
sw a1 sp -28
fadd a3 a2 a1
lw a1 sp -24
```

これに対して時間優先のスケジューリングを行った結果を下に示す。

```
1: lw a1 sp -32: -9
2: sw a1 sp -28: -4
3: fadd a3 a2 a1: -7
4: lw a1 sp -24: -2
time: 0
        1: lw a1 sp -32
time: 2
        3: fadd a3 a2 a1
        2: sw a1 sp -28
time: 7
        4: lw a1 sp -24
```

3行目の `fadd` は右辺に `a1` を含み、同じく `a1` を含む `sw` よりも後ろに配置されているが、`sw` における `a1` は右辺に相当するので、この2つの命令の間に依存関係はない。スケジューリングもそれを反映したものになっており、`sw` の依存関係も正しく理解できていることがわかる。

### スケジューリング戦略

実行方法で示した実行結果（時間優先によるスケジューリング）を改めて示す。

```
1: lw a1 sp -32: -14
2: lw a2 a1 0: -12
3: lw a3 sp -32: -14
4: lw a4 a3 4: -12
5: fadd a5 a2 a4: -10
6: lw a6 sp -24: -9
7: lw a7 a6 8: -7
8: fadd a8 a5 a7: -5
time: 0
        1: lw a1 sp -32
time: 2
        3: lw a3 sp -32
time: 4
        4: lw a4 a3 4
time: 6
        2: lw a2 a1 0
time: 8
        5: fadd a5 a2 a4
        6: lw a6 sp -24
time: 10
        7: lw a7 a6 8
time: 13
        8: fadd a8 a5 a7
```

同じ命令列に資源優先でスケジューリングを行った場合の結果を示す。

```
1: lw a1 sp -32: -1
2: lw a2 a1 0: -2
3: lw a3 sp -32: -1
4: lw a4 a3 4: -2
5: fadd a5 a2 a4: -3
6: lw a6 sp -24: -1
7: lw a7 a6 8: -2
8: fadd a8 a5 a7: -4
time: 0
        1: lw a1 sp -32
time: 2
        2: lw a2 a1 0
time: 4
        6: lw a6 sp -24
time: 6
        7: lw a7 a6 8
time: 8
        3: lw a3 sp -32
time: 10
        4: lw a4 a3 4
time: 12
        5: fadd a5 a2 a4
time: 17
        8: fadd a8 a5 a7
```

ともに8行目の命令が最後の実行されているが、実行開始時刻は時間優先のスケジューリングのほうが早い。もしレジスタ割り当て後にスケジューリングがされているなら、依存グラフの通りに実行していけば実行中に資源が不足することはないので、時間優先のほうが優れている。一方でスケジューリング後にレジスタ割り当てがされる場合、時間優先方式ではレジスタが不足し、ロード/ストアを余分に挿入する可能性がある。この場合、資源優先のほうが優れている可能性があると考えられる。