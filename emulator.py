#!/usr/bin/env python3
"""
Emulator for custom 16-bit processor architecture.

Instruction groups:
  00 - Memory operations (MOV, STORE, LOAD, MOV H/L)
  01 - ALU operations
  10 - BU operations (branches, CAL, RET)
  11 - System operations (INT, IRET, SEI, CLI, SWPB, MOVB, MUL, DIV)
"""

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

NUM_BANKS       = 4
NUM_REGS        = 7       # REG0..REG6 per bank
RAM_SIZE        = 0x10000 # 65536 words
VECTOR_TABLE    = 0x0000  # interrupt vectors start here (64 entries)
PROGRAM_START   = 0x0040  # user program starts after vector table

# FLAGS bits
CF = 0   # carry
ZF = 1   # zero
SF = 2   # sign
OF = 3   # overflow
IF = 4   # interrupt enable
BF0 = 5  # bank select bit 0
BF1 = 6  # bank select bit 1

# Shift types (used in MOV)
SHIFT_NONE  = 0b00
SHIFT_LSL   = 0b01  # logical shift left
SHIFT_LSR   = 0b10  # logical shift right
SHIFT_ASR   = 0b11  # arithmetic shift right

# Register index for COUNTER in instruction encoding
COUNTER_IDX = 0b111

# Stack buffer size (36 entries x 9 values each = 4 call levels)
STACK_BUFFER_SIZE = 36
STACK_ENTRY_SIZE  = 9   # COUNTER + FLAGS + BANK1 REG0..REG6

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def to_signed16(v: int) -> int:
    """Convert unsigned 16-bit value to signed."""
    v &= 0xFFFF
    return v if v < 0x8000 else v - 0x10000

def mask16(v: int) -> int:
    return v & 0xFFFF

# ─────────────────────────────────────────────
# CPU
# ─────────────────────────────────────────────

class CPU:
    def __init__(self, ram: list[int] | None = None, debug: bool = False):
        # 4 banks x 7 registers
        self.banks: list[list[int]] = [[0] * NUM_REGS for _ in range(NUM_BANKS)]
        self.counter: int = PROGRAM_START
        self.flags: int = 0          # FLAGS register
        self.ram: list[int] = ram if ram else [0] * RAM_SIZE
        self.sc: int = RAM_SIZE - 1  # stack counter, grows downward
        self.debug: bool = debug
        self.halted: bool = False
        self.cycles: int = 0

        # Hardware call stack buffer: list of 9-element entries
        self._call_buf: list[list[int]] = []

        # Pending hardware interrupt number (-1 = none)
        self._pending_irq: int = -1

    # ── flag helpers ──────────────────────────

    def _get_flag(self, bit: int) -> int:
        return (self.flags >> bit) & 1

    def _set_flag(self, bit: int, val: int) -> None:
        if val:
            self.flags |= (1 << bit)
        else:
            self.flags &= ~(1 << bit)

    @property
    def bank_idx(self) -> int:
        return (self._get_flag(BF1) << 1) | self._get_flag(BF0)

    @bank_idx.setter
    def bank_idx(self, v: int) -> None:
        self._set_flag(BF0, v & 1)
        self._set_flag(BF1, (v >> 1) & 1)

    # ── register access ───────────────────────

    def _read_reg(self, idx: int) -> int:
        """Read register by 3-bit index from current bank."""
        if idx == COUNTER_IDX:
            return self.counter
        return self.banks[self.bank_idx][idx]

    def _write_reg(self, idx: int, val: int) -> None:
        """Write register by 3-bit index in current bank."""
        val = mask16(val)
        if idx == COUNTER_IDX:
            self.counter = val
        else:
            self.banks[self.bank_idx][idx] = val

    def _read_reg_in_bank(self, bank: int, idx: int) -> int:
        if idx == COUNTER_IDX:
            return self.counter
        return self.banks[bank][idx]

    def _write_reg_in_bank(self, bank: int, idx: int, val: int) -> None:
        val = mask16(val)
        if idx == COUNTER_IDX:
            self.counter = val
        else:
            self.banks[bank][idx] = val

    # ── flag update after ALU ─────────────────

    def _update_flags(self, result: int, carry: int = 0, overflow: int = 0) -> None:
        r16 = mask16(result)
        self._set_flag(ZF, 1 if r16 == 0 else 0)
        self._set_flag(SF, (r16 >> 15) & 1)
        self._set_flag(CF, carry)
        self._set_flag(OF, overflow)

    # ── RAM helpers ───────────────────────────

    def _ram_read(self, addr: int) -> int:
        addr = mask16(addr)
        return self.ram[addr]

    def _ram_write(self, addr: int, val: int) -> None:
        addr = mask16(addr)
        self.ram[addr] = mask16(val)

    # ── hardware call stack buffer ────────────

    def _buf_push(self) -> None:
        """Save COUNTER, FLAGS, BANK1 REG0-REG6 into buffer (or RAM if full)."""
        entry = [self.counter, self.flags] + self.banks[1][:]
        if len(self._call_buf) * STACK_ENTRY_SIZE < STACK_BUFFER_SIZE:
            self._call_buf.append(entry)
        else:
            # spill oldest entry to RAM
            oldest = self._call_buf.pop(0)
            for v in oldest:
                self._ram_write(self.sc, v)
                self.sc = mask16(self.sc - 1)
            self._call_buf.append(entry)

    def _buf_pop(self) -> None:
        """Restore COUNTER, FLAGS, BANK1 REG0-REG6 from buffer (or RAM)."""
        if self._call_buf:
            entry = self._call_buf.pop()
        else:
            # reload from RAM
            entry = []
            for _ in range(STACK_ENTRY_SIZE):
                self.sc = mask16(self.sc + 1)
                entry.insert(0, self._ram_read(self.sc))
        self.counter   = entry[0]
        self.flags     = entry[1]
        self.banks[1]  = entry[2:]

    # ── interrupt handling ────────────────────

    def trigger_interrupt(self, vector: int) -> None:
        """Trigger hardware interrupt (called externally or by INT instruction)."""
        if not self._get_flag(IF):
            return  # interrupts disabled
        self._pending_irq = vector & 0x3F

    def _handle_interrupt(self, vector: int) -> None:
        # save COUNTER and FLAGS onto interrupt stack in RAM
        self._ram_write(self.sc, self.counter)
        self.sc = mask16(self.sc - 1)
        self._ram_write(self.sc, self.flags)
        self.sc = mask16(self.sc - 1)
        # force BANK3, disable interrupts
        self.bank_idx = 3
        self._set_flag(IF, 0)
        # jump to vector
        handler_addr = self._ram_read(VECTOR_TABLE + vector)
        self.counter = handler_addr

    # ─────────────────────────────────────────
    # Instruction execution
    # ─────────────────────────────────────────

    def step(self) -> None:
        """Execute one instruction."""
        if self.halted:
            return

        # check pending interrupt before fetching
        if self._pending_irq >= 0 and self._get_flag(IF):
            self._handle_interrupt(self._pending_irq)
            self._pending_irq = -1
            self.cycles += 1
            return

        instr = self._ram_read(self.counter)
        self.counter = mask16(self.counter + 1)
        self.cycles += 1

        group = (instr >> 14) & 0b11

        if group == 0b00:
            self._exec_memory(instr)
        elif group == 0b01:
            self._exec_alu(instr)
        elif group == 0b10:
            self._exec_bu(instr)
        elif group == 0b11:
            self._exec_system(instr)

        if self.debug:
            self._dump_state(instr)

    def run(self, max_cycles: int = 1_000_000) -> None:
        """Run until halted or max_cycles reached."""
        for _ in range(max_cycles):
            if self.halted:
                break
            self.step()

    # ─────────────────────────────────────────
    # 00 - Memory
    # ─────────────────────────────────────────

    def _exec_memory(self, instr: int) -> None:
        sub = (instr >> 12) & 0b11

        if sub == 0b00:
            # MOV reg reg [shift_mag 4bit] [shift_type 2bit]
            from_idx    = (instr >> 9) & 0b111
            to_idx      = (instr >> 6) & 0b111
            shift_mag   = (instr >> 2) & 0b1111
            shift_type  = instr & 0b11

            val = self._read_reg(from_idx)
            val = self._apply_shift(val, shift_mag, shift_type)
            self._write_reg(to_idx, val)

        elif sub == 0b01:
            # STORE reg(data) reg(address)
            from_idx = (instr >> 9) & 0b111
            to_idx   = (instr >> 6) & 0b111
            data     = self._read_reg(from_idx)
            addr     = self._read_reg(to_idx)
            self._ram_write(addr, data)

        elif sub == 0b10:
            # LOAD reg(address) reg(destination)
            from_idx = (instr >> 9) & 0b111
            to_idx   = (instr >> 6) & 0b111
            addr     = self._read_reg(from_idx)
            val      = self._ram_read(addr)
            self._write_reg(to_idx, val)

        elif sub == 0b11:
            # MOV H/L  immediate 8-bit into reg
            # bit 11 = H(1) or L(0)
            is_high  = (instr >> 11) & 1
            data     = (instr >> 3) & 0xFF
            to_idx   = instr & 0b111
            current  = self._read_reg(to_idx) if to_idx != COUNTER_IDX else self.counter
            if is_high:
                val = (current & 0x00FF) | (data << 8)
            else:
                val = (current & 0xFF00) | data
            self._write_reg(to_idx, mask16(val))

    def _apply_shift(self, val: int, mag: int, stype: int) -> int:
        val = mask16(val)
        if mag == 0 or stype == SHIFT_NONE:
            return val
        if stype == SHIFT_LSL:
            return mask16(val << mag)
        if stype == SHIFT_LSR:
            return val >> mag
        if stype == SHIFT_ASR:
            signed = to_signed16(val)
            return mask16(signed >> mag)
        return val

    # ─────────────────────────────────────────
    # 01 - ALU
    # ─────────────────────────────────────────

    def _exec_alu(self, instr: int) -> None:
        opcode     = (instr >> 9) & 0b1111  # bits 12..9
        arg1_idx   = (instr >> 6) & 0b111
        arg2_idx   = (instr >> 3) & 0b111
        result_idx = instr & 0b111

        a = self._read_reg(arg1_idx)
        b = self._read_reg(arg2_idx)

        carry    = 0
        overflow = 0
        result   = 0
        write    = True

        if opcode == 0b0000:   # AND
            result = a & b
        elif opcode == 0b0001: # NAND
            result = mask16(~(a & b))
        elif opcode == 0b0010: # NOR
            result = mask16(~(a | b))
        elif opcode == 0b0011: # OR
            result = a | b
        elif opcode == 0b0100: # XOR
            result = a ^ b
        elif opcode == 0b0101: # XNOR
            result = mask16(~(a ^ b))
        elif opcode == 0b0110: # MAX
            result = max(a, b)
        elif opcode == 0b0111: # MIN
            result = min(a, b)
        elif opcode == 0b1000: # ADD
            r = a + b
            carry    = 1 if r > 0xFFFF else 0
            overflow = 1 if to_signed16(a) + to_signed16(b) != to_signed16(r) else 0
            result   = mask16(r)
        elif opcode == 0b1001: # SUB
            r = a - b
            carry    = 1 if r < 0 else 0
            overflow = 1 if to_signed16(a) - to_signed16(b) != to_signed16(r) else 0
            result   = mask16(r)
        elif opcode == 0b1010: # ADC
            cf = self._get_flag(CF)
            r  = a + b + cf
            carry    = 1 if r > 0xFFFF else 0
            overflow = 1 if to_signed16(a) + to_signed16(b) + cf != to_signed16(r) else 0
            result   = mask16(r)
        elif opcode == 0b1011: # SBB
            cf = self._get_flag(CF)
            r  = a - b - cf
            carry    = 1 if r < 0 else 0
            overflow = 1 if to_signed16(a) - to_signed16(b) - cf != to_signed16(r) else 0
            result   = mask16(r)
        elif opcode == 0b1100: # CMP
            r = a - b
            carry    = 1 if r < 0 else 0
            overflow = 1 if to_signed16(a) - to_signed16(b) != to_signed16(r) else 0
            result   = mask16(r)
            write    = False  # CMP does not write result
        elif opcode == 0b1101: # GETF
            result = self.flags
        elif opcode == 0b1110: # SETF
            self.flags = mask16(a)
            return       # skip normal flag update
        elif opcode == 0b1111: # NOP
            return

        self._update_flags(result, carry, overflow)
        if write:
            self._write_reg(result_idx, result)

    # ─────────────────────────────────────────
    # 10 - BU
    # ─────────────────────────────────────────

    def _exec_bu(self, instr: int) -> None:
        opcode   = (instr >> 11) & 0b111
        signed   = (instr >> 10) & 1
        # bit 9 reserved
        arg1_idx = (instr >> 6) & 0b111
        arg2_idx = (instr >> 3) & 0b111
        jump_idx = instr & 0b111

        if opcode == 0b110:
            # CAL
            target = self._read_reg(arg1_idx)
            self._buf_push()
            self.counter = target
            return

        if opcode == 0b111:
            # RET
            self._buf_pop()
            return

        # conditional branch
        a = self._read_reg(arg1_idx)
        b = self._read_reg(arg2_idx)

        if signed:
            a_cmp = to_signed16(a)
            b_cmp = to_signed16(b)
        else:
            a_cmp = a
            b_cmp = b

        taken = False
        if opcode == 0b000:   taken = a_cmp == b_cmp   # BEQ
        elif opcode == 0b001: taken = a_cmp != b_cmp   # BNE
        elif opcode == 0b010: taken = a_cmp <  b_cmp   # BLT
        elif opcode == 0b011: taken = a_cmp <= b_cmp   # BLE
        elif opcode == 0b100: taken = a_cmp >  b_cmp   # BGT
        elif opcode == 0b101: taken = a_cmp >= b_cmp   # BGE

        if taken:
            self.counter = self._read_reg(jump_idx)

    # ─────────────────────────────────────────
    # 11 - System
    # ─────────────────────────────────────────

    def _exec_system(self, instr: int) -> None:
        opcode = (instr >> 11) & 0b111

        if opcode == 0b000:
            # INT vector(6 bits)
            vector = (instr >> 3) & 0b111111
            self._handle_interrupt(vector)

        elif opcode == 0b001:
            # IRET
            self.flags   = self._ram_read(mask16(self.sc + 1))
            self.sc      = mask16(self.sc + 1)
            self.counter = self._ram_read(mask16(self.sc + 1))
            self.sc      = mask16(self.sc + 1)
            self._set_flag(IF, 1)

        elif opcode == 0b010:
            # SEI
            self._set_flag(IF, 1)

        elif opcode == 0b011:
            # CLI
            self._set_flag(IF, 0)

        elif opcode == 0b100:
            # SWPB bank(2 bits)
            bank = (instr >> 9) & 0b11
            if bank == 3:
                raise RuntimeError("SWPB: BANK3 is forbidden for user code")
            self.bank_idx = bank

        elif opcode == 0b101:
            # MOVB from_bank(2) from_reg(3) to_bank(2) to_reg(3)
            # bits 10-9 = from_bank, 8-6 = from_reg, 5-4(wait 3bits) to_bank, 2-0 to_reg
            from_bank = (instr >> 9) & 0b11
            from_reg  = (instr >> 6) & 0b111
            to_bank   = (instr >> 3) & 0b11
            to_reg    = instr & 0b111
            if from_bank == 3 or to_bank == 3:
                raise RuntimeError("MOVB: BANK3 is forbidden for user code")
            val = self._read_reg_in_bank(from_bank, from_reg)
            self._write_reg_in_bank(to_bank, to_reg, val)

        elif opcode == 0b110:
            # MUL arg1 arg2 → BANK2.REG0 (low), BANK2.REG1 (high)
            arg1_idx = (instr >> 6) & 0b111
            arg2_idx = (instr >> 3) & 0b111
            a = self._read_reg(arg1_idx)
            b = self._read_reg(arg2_idx)
            r = a * b
            low  = mask16(r)
            high = mask16(r >> 16)
            self.banks[2][0] = low
            self.banks[2][1] = high
            carry    = 1 if high != 0 else 0
            overflow = 1 if r > 0x7FFF else 0
            self._update_flags(low, carry, overflow)

        elif opcode == 0b111:
            # DIV arg1 / arg2 → BANK2.REG0 (quotient), BANK2.REG1 (remainder)
            arg1_idx = (instr >> 6) & 0b111
            arg2_idx = (instr >> 3) & 0b111
            a = self._read_reg(arg1_idx)
            b = self._read_reg(arg2_idx)
            if b == 0:
                self._set_flag(CF, 1)  # division by zero
                return
            quotient  = a // b
            remainder = a % b
            self.banks[2][0] = mask16(quotient)
            self.banks[2][1] = mask16(remainder)
            carry    = 0
            overflow = 1 if quotient > 0xFFFF else 0
            self._update_flags(mask16(quotient), carry, overflow)

    # ─────────────────────────────────────────
    # Debug
    # ─────────────────────────────────────────

    def _dump_state(self, instr: int) -> None:
        b = self.bank_idx
        regs = " ".join(f"R{i}={self.banks[b][i]:04X}" for i in range(NUM_REGS))
        cf = self._get_flag(CF)
        zf = self._get_flag(ZF)
        sf = self._get_flag(SF)
        of = self._get_flag(OF)
        print(f"[{self.cycles:6d}] PC={self.counter:04X} BANK={b} | {regs} "
              f"| CF={cf} ZF={zf} SF={sf} OF={of} | INSTR={instr:016b}")

    def dump(self) -> None:
        """Print full CPU state."""
        print("=" * 60)
        print(f"COUNTER : {self.counter:04X}  SC: {self.sc:04X}  "
              f"FLAGS: {self.flags:04X}  CYCLES: {self.cycles}")
        print(f"Active bank: BANK{self.bank_idx}")
        for b in range(NUM_BANKS):
            regs = "  ".join(f"R{i}={self.banks[b][i]:04X}" for i in range(NUM_REGS))
            print(f"  BANK{b}: {regs}")
        print(f"Call buffer depth: {len(self._call_buf)}")
        print("=" * 60)


# ─────────────────────────────────────────────
# Assembler (simple single-pass)
# ─────────────────────────────────────────────

class Assembler:
    """
    Simple assembler for the custom 16-bit architecture.

    Syntax examples:
      MOV  R0 R1              ; copy R0 → R1, no shift
      MOV  R0 R1 4 LSL        ; copy R0 → R1 with left shift by 4
      MOVH R0 0xFF            ; load 0xFF into high byte of R0
      MOVL R0 0x05            ; load 0x05 into low byte of R0
      STORE R0 R1             ; RAM[R1] = R0
      LOAD  R0 R1             ; R1 = RAM[R0]
      ADD  R0 R1 R2           ; R2 = R0 + R1
      SUB  R0 R1 R2
      ADC  R0 R1 R2
      SBB  R0 R1 R2
      AND  R0 R1 R2
      NAND R0 R1 R2
      NOR  R0 R1 R2
      OR   R0 R1 R2
      XOR  R0 R1 R2
      XNOR R0 R1 R2
      MAX  R0 R1 R2
      MIN  R0 R1 R2
      CMP  R0 R1              ; flags only
      GETF R0                 ; R0 = FLAGS
      SETF R0                 ; FLAGS = R0
      NOP
      BEQ  R0 R1 R2           ; if R0 == R1 jump to address in R2  (unsigned)
      BEQS R0 R1 R2           ; signed version
      BNE  R0 R1 R2
      BNES R0 R1 R2
      BLT  R0 R1 R2
      BLTS R0 R1 R2
      BLE  R0 R1 R2
      BLES R0 R1 R2
      BGT  R0 R1 R2
      BGTS R0 R1 R2
      BGE  R0 R1 R2
      BGES R0 R1 R2
      CAL  R0                 ; call function at address in R0
      RET
      INT  5                  ; software interrupt vector 5
      IRET
      SEI
      CLI
      SWPB BANK0              ; switch to BANK0
      MOVB B0.R0 B1.R1        ; copy BANK0.R0 to BANK1.R1
      MUL  R0 R1              ; BANK2.R0=low, BANK2.R1=high
      DIV  R0 R1              ; BANK2.R0=quotient, BANK2.R1=remainder
      HALT                    ; pseudo: write 0xFFFF (caught by emulator)
      label:                  ; define label
      .word 0x1234            ; raw 16-bit value
      .org 0x0040             ; set current address
    """

    REG_MAP = {
        "R0": 0, "R1": 1, "R2": 2, "R3": 3,
        "R4": 4, "R5": 5, "R6": 6,
        "COUNTER": 7, "PC": 7,
    }

    BANK_MAP = {"BANK0": 0, "BANK1": 1, "BANK2": 2}

    SHIFT_MAP = {"NONE": 0, "LSL": 1, "LSR": 2, "ASR": 3}

    ALU_MAP = {
        "AND": 0x0, "NAND": 0x1, "NOR": 0x2, "OR": 0x3,
        "XOR": 0x4, "XNOR": 0x5, "MAX": 0x6, "MIN": 0x7,
        "ADD": 0x8, "SUB": 0x9, "ADC": 0xA, "SBB": 0xB,
    }

    BU_MAP = {
        "BEQ": (0, 1), "BEQS": (0, 0),
        "BNE": (1, 1), "BNES": (1, 0),
        "BLT": (2, 1), "BLTS": (2, 0),
        "BLE": (3, 1), "BLES": (3, 0),
        "BGT": (4, 1), "BGTS": (4, 0),
        "BGE": (5, 1), "BGES": (5, 0),
    }

    def __init__(self):
        self.ram   = [0] * RAM_SIZE
        self.pc    = PROGRAM_START
        self.labels: dict[str, int] = {}
        self.errors: list[str] = []

    def _reg(self, s: str) -> int:
        s = s.upper().strip().rstrip(",")
        if s not in self.REG_MAP:
            raise ValueError(f"Unknown register: {s}")
        return self.REG_MAP[s]

    def _imm(self, s: str) -> int:
        s = s.strip().rstrip(",")
        return int(s, 0)

    def _emit(self, word: int) -> None:
        self.ram[self.pc] = mask16(word)
        self.pc += 1

    def assemble(self, source: str) -> list[int]:
        lines = source.splitlines()

        # first pass: collect labels
        addr = PROGRAM_START
        for raw in lines:
            line = raw.split(";")[0].strip()
            if not line:
                continue
            if line.startswith(".org"):
                addr = int(line.split()[1], 0)
                continue
            if line.endswith(":"):
                self.labels[line[:-1].strip()] = addr
                continue
            if line.startswith(".word"):
                addr += 1
                continue
            addr += 1

        # second pass: emit
        self.pc = PROGRAM_START
        for lineno, raw in enumerate(lines, 1):
            line = raw.split(";")[0].strip()
            if not line:
                continue
            try:
                self._assemble_line(line)
            except Exception as e:
                self.errors.append(f"Line {lineno}: {e}  →  {raw.strip()}")

        return self.ram

    def _assemble_line(self, line: str) -> None:
        if line.endswith(":"):
            return  # label already handled

        if line.startswith(".org"):
            self.pc = int(line.split()[1], 0)
            return

        if line.startswith(".word"):
            val = int(line.split()[1], 0)
            self._emit(val)
            return

        tokens = line.split()
        op = tokens[0].upper()

        # ── Memory ──
        if op == "MOV":
            # MOV src dst [mag] [type]
            src = self._reg(tokens[1])
            dst = self._reg(tokens[2])
            mag  = int(tokens[3]) if len(tokens) > 3 else 0
            stype = self.SHIFT_MAP.get(tokens[4].upper(), 0) if len(tokens) > 4 else 0
            word = (0b0000 << 12) | (src << 9) | (dst << 6) | (mag << 2) | stype
            self._emit(word)

        elif op == "STORE":
            src  = self._reg(tokens[1])
            addr = self._reg(tokens[2])
            word = (0b0001 << 12) | (src << 9) | (addr << 6)
            self._emit(word)

        elif op == "LOAD":
            addr = self._reg(tokens[1])
            dst  = self._reg(tokens[2])
            word = (0b0010 << 12) | (addr << 9) | (dst << 6)
            self._emit(word)

        elif op == "MOVH":
            dst  = self._reg(tokens[1])
            data = self._imm(tokens[2]) & 0xFF
            word = (0b0011 << 12) | (1 << 11) | (data << 3) | dst
            self._emit(word)

        elif op == "MOVL":
            dst  = self._reg(tokens[1])
            data = self._imm(tokens[2]) & 0xFF
            word = (0b0011 << 12) | (0 << 11) | (data << 3) | dst
            self._emit(word)

        # ── ALU ──
        elif op in self.ALU_MAP:
            opcode = self.ALU_MAP[op]
            a = self._reg(tokens[1])
            b = self._reg(tokens[2])
            r = self._reg(tokens[3])
            word = (0b01 << 14) | (opcode << 9) | (a << 6) | (b << 3) | r
            self._emit(word)

        elif op == "CMP":
            a = self._reg(tokens[1])
            b = self._reg(tokens[2])
            word = (0b01 << 14) | (0xC << 9) | (a << 6) | (b << 3)
            self._emit(word)

        elif op == "GETF":
            r = self._reg(tokens[1])
            word = (0b01 << 14) | (0xD << 9) | r
            self._emit(word)

        elif op == "SETF":
            a = self._reg(tokens[1])
            word = (0b01 << 14) | (0xE << 9) | (a << 6)
            self._emit(word)

        elif op == "NOP":
            word = (0b01 << 14) | (0xF << 9)
            self._emit(word)

        # ── BU ──
        elif op in self.BU_MAP:
            opcode, unsigned = self.BU_MAP[op]
            a    = self._reg(tokens[1])
            b    = self._reg(tokens[2])
            jump = self._reg(tokens[3])
            word = (0b10 << 14) | (opcode << 11) | (unsigned << 10) | (a << 6) | (b << 3) | jump
            self._emit(word)

        elif op == "CAL":
            arg = self._reg(tokens[1])
            word = (0b10 << 14) | (0b110 << 11) | (arg << 6)
            self._emit(word)

        elif op == "RET":
            word = (0b10 << 14) | (0b111 << 11)
            self._emit(word)

        # ── System ──
        elif op == "INT":
            vector = self._imm(tokens[1]) & 0x3F
            word = (0b11 << 14) | (0b000 << 11) | (vector << 3)
            self._emit(word)

        elif op == "IRET":
            word = (0b11 << 14) | (0b001 << 11)
            self._emit(word)

        elif op == "SEI":
            word = (0b11 << 14) | (0b010 << 11)
            self._emit(word)

        elif op == "CLI":
            word = (0b11 << 14) | (0b011 << 11)
            self._emit(word)

        elif op == "SWPB":
            bank = self.BANK_MAP.get(tokens[1].upper(), 0)
            word = (0b11 << 14) | (0b100 << 11) | (bank << 9)
            self._emit(word)

        elif op == "MOVB":
            # MOVB B0.R0 B1.R1
            # encoding: 11 101 [2 from_bank] [3 from_reg] [2 to_bank] [3 to_reg]
            # bits:     15-14  13-11  10-9       8-6         5-4        3-1  0(unused)
            def parse_bank_reg(s):
                s = s.upper().strip().rstrip(",")
                parts = s.split(".")
                b = int(parts[0][1])
                r = self.REG_MAP[parts[1]]
                return b, r
            fb, fr = parse_bank_reg(tokens[1])
            tb, tr = parse_bank_reg(tokens[2])
            word = (0b11 << 14) | (0b101 << 11) | (fb << 9) | (fr << 6) | (tb << 3) | tr
            self._emit(word)

        elif op == "MUL":
            a = self._reg(tokens[1])
            b = self._reg(tokens[2])
            word = (0b11 << 14) | (0b110 << 11) | (a << 6) | (b << 3)
            self._emit(word)

        elif op == "DIV":
            a = self._reg(tokens[1])
            b = self._reg(tokens[2])
            word = (0b11 << 14) | (0b111 << 11) | (a << 6) | (b << 3)
            self._emit(word)

        elif op == "HALT":
            self._emit(0xFFFF)

        else:
            raise ValueError(f"Unknown instruction: {op}")


# ─────────────────────────────────────────────
# HALT trap
# ─────────────────────────────────────────────

class HaltTrap(CPU):
    """CPU subclass that stops on 0xFFFF instruction."""
    def step(self):
        instr = self.ram[self.counter]
        if instr == 0xFFFF:
            self.halted = True
            return
        super().step()


# ─────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────

def run_test(name: str, source: str, check) -> None:
    asm = Assembler()
    ram = asm.assemble(source)
    if asm.errors:
        print(f"[FAIL] {name}")
        for e in asm.errors:
            print(f"  {e}")
        return
    cpu = HaltTrap(ram=ram)
    cpu.run()
    try:
        check(cpu)
        print(f"[PASS] {name}")
    except AssertionError as e:
        print(f"[FAIL] {name}: {e}")
        cpu.dump()


def assert_eq(actual, expected, msg=""):
    assert actual == expected, f"{msg} — got {actual:#06x}, expected {expected:#06x}"


if __name__ == "__main__":

    # ── Test 1: basic ADD ─────────────────────
    run_test("ADD R0+R1=R2", """
        MOVL R0 10
        MOVL R1 20
        ADD  R0 R1 R2
        HALT
    """, lambda cpu: (
        assert_eq(cpu.banks[0][2], 30, "R2 should be 30")
    ))

    # ── Test 2: SUB with flags ────────────────
    run_test("SUB flags ZF", """
        MOVL R0 5
        MOVL R1 5
        SUB  R0 R1 R2
        HALT
    """, lambda cpu: (
        assert_eq(cpu.banks[0][2], 0, "R2 should be 0"),
        assert_eq((cpu.flags >> ZF) & 1, 1, "ZF should be 1")
    ))

    # ── Test 3: MOV with shift ────────────────
    run_test("MOV LSL shift", """
        MOVL R0 1
        MOV  R0 R1 4 LSL
        HALT
    """, lambda cpu: (
        assert_eq(cpu.banks[0][1], 16, "R1 should be 16 (1<<4)")
    ))

    # ── Test 4: STORE and LOAD ────────────────
    run_test("STORE/LOAD", """
        MOVL R0 0xAB
        MOVL R1 0x50
        STORE R0 R1
        MOVL  R2 0
        LOAD  R1 R2
        HALT
    """, lambda cpu: (
        assert_eq(cpu.banks[0][2], 0xAB, "R2 should be 0xAB")
    ))

    # ── Test 5: CAL/RET ───────────────────────
    run_test("CAL/RET", """
        .org 0x0040
        MOVL R0 5
        MOVH R6 0x00
        MOVL R6 0x50
        CAL  R6
        HALT
        .org 0x0050
        ADD R0 R0 R0
        RET
    """, lambda cpu: (
        assert_eq(cpu.banks[0][0], 10, "R0 should be 10 after CAL")
    ))

    # ── Test 6: BEQ branch taken ──────────────
    run_test("BEQ taken", """
        .org 0x0040
        MOVL R0 7
        MOVL R1 7
        MOVH R2 0x00
        MOVL R2 0x48
        BEQ  R0 R1 R2
        MOVL R3 0xFF
        HALT
        .org 0x0048
        MOVL R3 0x11
        HALT
    """, lambda cpu: (
        assert_eq(cpu.banks[0][3], 0x11, "R3 should be 0x11 (branch taken)")
    ))

    # ── Test 7: MUL ───────────────────────────
    run_test("MUL 100*200", """
        MOVL R0 100
        MOVL R1 200
        MUL  R0 R1
        HALT
    """, lambda cpu: (
        assert_eq(cpu.banks[2][0], 20000, "BANK2.R0 should be 20000")
    ))

    # ── Test 8: DIV ───────────────────────────
    run_test("DIV 17/5", """
        MOVL R0 17
        MOVL R1 5
        DIV  R0 R1
        HALT
    """, lambda cpu: (
        assert_eq(cpu.banks[2][0], 3, "quotient should be 3"),
        assert_eq(cpu.banks[2][1], 2, "remainder should be 2")
    ))

    # ── Test 9: MOVH/MOVL full 16-bit ────────
    run_test("MOVH+MOVL = 0x1234", """
        MOVH R0 0x12
        MOVL R0 0x34
        HALT
    """, lambda cpu: (
        assert_eq(cpu.banks[0][0], 0x1234, "R0 should be 0x1234")
    ))

    # ── Test 10: SWPB + MOVB ─────────────────
    run_test("SWPB + MOVB", """
        MOVL R0 42
        MOVB B0.R0 B1.R3
        SWPB BANK1
        HALT
    """, lambda cpu: (
        assert_eq(cpu.banks[1][3], 42, "BANK1.R3 should be 42")
    ))

    print("\nDone.")
