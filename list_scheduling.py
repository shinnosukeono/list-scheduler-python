import heapq as hq
import sys
from dataclasses import dataclass
from enum import Enum
from functools import total_ordering


# types of operation
class Ops(int, Enum):
    ADD = 0
    MUL = 1
    FADD = 2
    FMUL = 3
    LW = 4
    SW = 5


# clocks necessary for each operation unit
@dataclass
class Clocks:
    ALU: int = 1
    FPU: int = 5
    MEMORY: int = 2


# state of instruction
class Status(int, Enum):
    NOT_STARTED = 0
    RUNNING = 1
    DONE = 2


# instruction class
@total_ordering
class Instr:
    def __init__(self, n: int, name: str, opecode: Ops, left: list[str], right: list[str]) -> None:
        self.n = n  # row number
        self.name = name  # display name
        self.opecode = opecode  # type of operation
        self.left = left  # left-hand side value
        self.right = right  # right-hand side value
        self.dependent_list: list[Instr] = []  # dependent instructions
        self.next_list: list[Instr] = []  # instructions that depend on myself
        self.priority = None  # priority (lower value has higher priority)
        self.t_start = None  # start time of execution
        self.t_end = None  # end time of execution

    def get_status(self) -> Status:
        """
        get the current status of the instruction
        """
        if self.t_end is None:
            if self.t_start is None:
                return Status.NOT_STARTED
            else:
                return Status.RUNNING
        else:
            return Status.DONE

    def update(self, t: int, clocks: int) -> None:
        """update the latency constraint

        Args:
            t (int): current time
            clocks (int): clocks necessary for this type of instruction
        """
        if self.t_start is not None:
            if t == self.t_start + clocks - 1:
                self.t_end = t

    # use priority for comparison between Instr(s)
    def __eq__(self, __value: object) -> bool:
        if not isinstance(__value, Instr):
            return NotImplemented
        return self.priority == __value.priority

    def __lt__(self, __value: object) -> bool:
        if not isinstance(__value, Instr):
            return NotImplemented
        return self.priority < __value.priority

    def __str__(self) -> str:
        return f"{self.n}: {self.name}"


# Operation unit class
class OpUnits:
    def __init__(self, n: int, clocks: int) -> None:
        self.n = n  # number of machines
        self.unit_list = [(0, False) for _ in range(n)]  # track the start time of execution and status of each machine
        self.clocks = clocks  # clocks necessary for operation
        self.n_busy = 0  # number of currently busy machines
        self.next = 0  # index of the machine to be allocated next

    def is_full(self) -> bool:
        """return all machines are busy or not"""
        return self.n == self.n_busy

    def allocate(self, t: int) -> int:
        """allocate a machine and update stats

        Args:
            t (int): current time

        Returns:
            int: index of the machine which was allocated
        """
        allocated = self.next  # allocate this
        self.unit_list[allocated] = (t, True)  # update status
        self.n_busy += 1

        # search for the index to be allocated next
        if self.n_busy < self.n:
            for i in range(1, self.n):
                if not self.unit_list[(allocated + i) % self.n][1]:
                    self.next = (allocated + i) % self.n
                    break

        return allocated

    def update(self, t: int) -> None:
        """update the resource constraint

        Args:
            t (int): current time
        """
        for unit in self.unit_list:
            if unit[1]:
                if t == unit[0] + self.clocks - 1:
                    unit = (unit[0], False)
                    self.n_busy -= 1


# scheduler class
class Scheduler:
    def __init__(self, n_alu: int, n_fpu: int, n_memory: int, priority_type: str, instr_list: list[Instr]) -> None:
        self.alu: OpUnits = OpUnits(n_alu, Clocks.ALU)  # ALU
        self.fpu: OpUnits = OpUnits(n_fpu, Clocks.FPU)  # FPU
        self.memory: OpUnits = OpUnits(n_memory, Clocks.MEMORY)  # MEMORY
        self.instr_wait_list: list[Instr] = instr_list  # list of instructions waiting for being sent to ready_set
        self.instr_dispatched_list: list[Instr] = []  # list of instructions already dispatched
        self.ready_set: list[Instr] = []  # priority queue of instructions that have no dependency currently
        if priority_type not in ["time", "resource"]:
            raise ValueError(
                f"Invalid priority type specified: {priority_type}." "A priority type must be 'time' or 'resource'."
            )
        else:
            self.priority_type = priority_type

    def _get_op_unit(self, instr: Instr) -> OpUnits:
        """get the operation unit which will process the instruction

        Args:
            instr (Instr): instruction

        Returns:
            OpUnits: corresponding operation unit
        """
        match instr.opecode:
            case Ops.ADD:
                return self.alu
            case Ops.MUL:
                return self.alu
            case Ops.FADD:
                return self.fpu
            case Ops.FMUL:
                return self.fpu
            case Ops.LW:
                return self.memory
            case Ops.SW:
                return self.memory

    def _set_dependency(self) -> None:
        """construct the dependency graph"""
        for i in range(len(self.instr_wait_list)):
            for j in range(0, i):
                for operand in self.instr_wait_list[i].right:
                    if operand in self.instr_wait_list[j].left:
                        # RAW dependency
                        self.instr_wait_list[i].dependent_list.append(self.instr_wait_list[j])
                        self.instr_wait_list[j].next_list.append(self.instr_wait_list[i])
                for operand in self.instr_wait_list[i].left:
                    if operand in self.instr_wait_list[j].left:
                        # WAW dependency
                        self.instr_wait_list[i].dependent_list.append(self.instr_wait_list[j])
                        self.instr_wait_list[j].next_list.append(self.instr_wait_list[i])
                    if operand in self.instr_wait_list[j].right:
                        # WAR dependency
                        self.instr_wait_list[i].dependent_list.append(self.instr_wait_list[j])
                        self.instr_wait_list[j].next_list.append(self.instr_wait_list[i])

    def _update_ready_set(self) -> None:
        """update ready set"""
        ready_set = []
        for instr in self.instr_wait_list:
            flag = True  # whether or not all the preceding instructions have been finished
            for dependent_instr in instr.dependent_list:
                if dependent_instr.get_status() != Status.DONE:
                    # not ready to dispatch if there is a preceding instruction not finished yet
                    flag = False
                    break
            if flag:
                # ready to dispatch
                # including there is no dependent instruction
                hq.heappush(self.ready_set, instr)
                ready_set.append(instr)

        # instructions sent to the ready set should be deleted from instr_wait_list
        for ready in ready_set:
            for i in range(len(self.instr_wait_list)):
                if ready is self.instr_wait_list[i]:
                    self.instr_wait_list.pop(i)
                    break

    def _find_critical_path(self) -> None:
        """give priority to all the instructions based on the length of the critical path, using Bellman-Ford method"""
        # set the time of executing myself as the initial value
        for instr in self.instr_wait_list:
            instr.priority = -self._get_op_unit(instr).clocks

        while True:
            updated = False  # whether or not any priority is updated
            for instr in self.instr_wait_list:
                for next_instr in instr.next_list:
                    if instr.priority > next_instr.priority - self._get_op_unit(instr).clocks:
                        instr.priority = (
                            next_instr.priority - self._get_op_unit(instr).clocks
                        )  # the weight of an edge is the clocks of the preceding instruction
                        updated = True

            if not updated:
                # break if there is no update
                break

    def _count_dependency(self) -> None:
        """give priority to all the instructions based on the depth of the dependency graph, using Bellman-Ford method"""
        # set the common value as the initial value
        for instr in self.instr_wait_list:
            instr.priority = -1

        while True:
            updated = False
            for instr in self.instr_wait_list:
                for dependent_instr in instr.dependent_list:
                    if instr.priority > dependent_instr.priority - 1:
                        instr.priority = dependent_instr.priority - 1
                        updated = True

            if not updated:
                break

    def _set_priority(self) -> None:
        """give priority to all the instructions"""
        match self.priority_type:
            case "time":
                self._find_critical_path()
            case "resource":
                self._count_dependency()

    def _dispatch(self, t: int) -> None:
        """dispatch an instruction and update constraints

        Args:
            t (int): current time
        """
        dispatched_list = []
        for instr in self.ready_set:
            # as ready_set was created as a priority queue, it is already sorted in the order of priority

            op_unit = self._get_op_unit(instr)

            if op_unit.is_full():
                # cannot allocate any operation unit
                continue
            else:
                # dispatch
                dispatched_list.append(instr)
                instr.t_start = t
                op_unit.allocate(t)

        if len(dispatched_list) > 0:
            # display the dispatched instructions
            print(f"time: {t}")
            for dispatched in dispatched_list:
                print(f"\t{dispatched}")

                # delete the dispatched from ready_set
                for i in range(len(self.ready_set)):
                    if dispatched is self.ready_set[i]:
                        self.ready_set.pop(i)
                        break

                self.instr_dispatched_list.append(dispatched)

        # update the latency constraint
        for instr in self.instr_dispatched_list:
            instr.update(t, self._get_op_unit(instr).clocks)

        # update the resource constraint
        self.alu.update(t)
        self.fpu.update(t)
        self.memory.update(t)

        # update ready set
        self._update_ready_set()

    def schedule(self) -> None:
        """schedule all the instructions"""
        self._set_dependency()  # construct the dependency graph
        self._set_priority()  # set the priority
        for instr in self.instr_wait_list:
            print(f"{instr}: {instr.priority}")

        t = 0  # begin scheduling
        self._update_ready_set()  # construct ready_set for the first time
        while len(self.instr_wait_list + self.ready_set) > 0:
            self._dispatch(t)
            t += 1


N_ALU = 2
N_FPU = 1
N_MEMORY = 1
if __name__ == "__main__":
    args = sys.argv
    filename = args[1]
    priority_type = args[2]
    with open(filename, "r", encoding="utf-8") as f:
        lines = f.readlines()
        instr_list: list[Instr] = []
        for i, line in enumerate(lines):
            line = line.rstrip("\n")
            line_parsed = line.split()
            match line_parsed[0]:
                case "add":
                    opecode = Ops.ADD
                    left = [line_parsed[1]]
                    right = [line_parsed[2], line_parsed[3]]
                case "mul":
                    opecode = Ops.MUL
                    left = [line_parsed[1]]
                    right = [line_parsed[2], line_parsed[3]]
                case "fadd":
                    opecode = Ops.FADD
                    left = [line_parsed[1]]
                    right = [line_parsed[2], line_parsed[3]]
                case "fmul":
                    opecode = Ops.FMUL
                    left = [line_parsed[1]]
                    right = [line_parsed[2], line_parsed[3]]
                case "lw":
                    opecode = Ops.LW
                    left = [line_parsed[1]]
                    right = [line_parsed[2]]
                case "sw":
                    opecode = Ops.SW
                    left = [line_parsed[2]]
                    right = [line_parsed[1]]
            instr_list.append(Instr(i + 1, line, opecode, left, right))
    scheduler = Scheduler(N_ALU, N_FPU, N_MEMORY, priority_type, instr_list)
    scheduler.schedule()
