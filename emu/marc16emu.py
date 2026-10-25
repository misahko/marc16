import math

M = 0xFFFF


def s16(x):
    x &= M

    return x - 0x10000 if x & 0x8000 else x


def s8(x):
    x &= 0xFF
    return x - 0x100 if x & 0x80 else x


def sexb(rs):
    return (((rs & 0xFF) ^ 0x80) - 0x80) & 0xFFFF


class Reg:
    def __init__(self, bus, addr):
        self.bus = bus
        self.addr = addr

    @property
    def v(self):
        return self.bus[self.addr]

    @v.setter
    def v(self, val):
        self.bus[self.addr] = val


class Sp:
    def __init__(self, sp_mode, usp, ksp):
        self.sp_mode = sp_mode
        self.usp = usp
        self.ksp = ksp

    @property
    def v(self):
        return self.usp.v if self.sp_mode.v else self.ksp.v

    @v.setter
    def v(self, val):
        if self.sp_mode.v:
            self.usp.v = val
        else:
            self.ksp.v = val


class Bit:
    def __init__(self, bus, addr, i, size):
        self.bus = bus
        self.addr = addr
        self.i = i
        self.size = size

    @property
    def v(self):
        return (self.bus[self.addr] >> self.i) & ((1 << self.size) - 1)

    @v.setter
    def v(self, val):
        tmp = self.bus[self.addr]
        tmp &= ~(((1 << self.size) - 1) << self.i) & 0xFFFF
        tmp |= (val & ((1 << self.size) - 1)) << self.i
        self.bus[self.addr] = tmp


class Bus:
    def __init__(self, size):
        self.mem = [0] * size
        self.size = size

    def __getitem__(self, i):
        if not 0 <= i < self.size:
            raise IndexError(i)
        return self.read(i)

    def __setitem__(self, i, v):
        if not 0 <= i < self.size:
            raise IndexError(i)

        self.write(i, v)

    def read(self, addr):
        return self.mem[addr]

    def write(self, addr, data):
        self.mem[addr] = data & 0xFFFF


class Rgf:
    def __init__(self, sp):
        self.rgs = [0] * 15
        self.sp = sp

    def __getitem__(self, i):
        if not 0 <= i < 16:
            raise IndexError(i)
        if i == 15:
            return self.sp.v
        else:
            return self.rgs[i]

    def __setitem__(self, i, val):
        if not 0 <= i < 16:
            raise IndexError(i)
        if i == 15:
            self.sp.v = val
        else:
            self.rgs[i] = val


class If:
    def __init__(self, passif, pc, bus, ifid):
        self.pc = pc
        self.bus = bus
        self.ifid = ifid
        self.passif = passif

    def step(self):
        if self.passif.v:
            self.ifid.v = None
            self.passif.v = False
            return

        self.ifid.v = (self.pc.v, self.bus[self.pc.v])
        self.pc.v += 1


class Id:
    def __init__(self, ifid, idex):
        self.ifid = ifid
        self.idex = idex
        self.op = 0

    def step(self):
        f = self.ifid.v
        if f is None:  # бульбашка
            self.idex.v = None
            return
        pc, w = f
        op = w & 7
        self.idex.v = (
            pc,  # 0 PC
            op,  # 1 OP
            (w >> 3) & (31 if op in (0, 1, 5, 7) else 1),  # 2 SUBOP
            (w >> 12) & 15,  # 3 RD
            (w >> 8) & 15,  # 4 RS
            (w >> 4) & 255,  # 5 IMM8
            (w >> 4) & 4095,  # 6 IMM12
            (w >> 4) & 15,  # 7 OFFSET4
        )


class Ex:
    def __init__(self, ifid, idex, exmem, alu, rgf, pc, passif):
        self.ifid, self.idex, self.exmem, self.alu, self.rgf, self.pc, self.passif = (
            ifid,
            idex,
            exmem,
            alu,
            rgf,
            pc,
            passif,
        )

    def step(self):
        d = self.idex.v
        if d is None:
            self.exmem.v = None
            return
        pc, op, subop, rd, rs, imm8, imm12, off4 = d
        res = None
        if op == 0:
            match subop:
                case 0:
                    res = self.rgf[rs]

                case 1:
                    res = (self.rgf[rs] >> 8 | self.rgf[rs] << 8) & 0xFFFF

                case 2:
                    res = self.rgf[rs] & 0x00FF

                case 3:
                    res = sexb(self.rgf[rs])

                case 4:
                    res = (self.rgf[rd] & 0x00FF) | (self.rgf[rs] << 8)

                case 5:
                    res = (self.rgf[rd] & 0xFF00) | (self.rgf[rs] & 0x00FF)

        elif op == 1:  # ALU
            res = self.alu.run(subop, self.rgf[rd], self.rgf[rs])
        elif op == 2:
            taken = (self.rgf[rd] == 0) if subop == 0 else (self.rgf[rd] != 0)
            if taken:
                self.ifid.v = None
                self.idex.v = None
                self.passif.v = True
                self.pc.v = self.alu.run(6, pc, s8(imm8), 1)

        elif op == 3:
            match subop:
                case 0:
                    pass
                case 1:
                    self.rgf[14] = self.alu.run(6, pc, cin=1)

            self.ifid.v = None
            self.idex.v = None
            self.passif.v = True
            self.pc.v = self.alu.run(6, pc, s8(imm8), 1)

        elif op == 4:
            match subop:
                case 0:
                    res = imm8 & 0xFFFF
                case 1:
                    res = (self.rgf[rd] & 0x00FF) | (imm8 << 8)

        elif op == 5:
            match subop:
                case 0:
                    pass

                case 1:
                    pass

                case 2:
                    pass

        elif op == 6:


        self.exmem.v = (pc, op, rd, res)  # rd = куди писати


class Mem:
    def __init__(self, bus, exmem, memwb):
        self.bus = bus
        self.memwb = memwb
        self.exmem = exmem

    def step(self):
        # read mem
        pass


class Wb:
    def __init__(self, rgf, memwb):
        self.rgf = rgf
        self.memwb = memwb

    def step(self):
        # save
        pass


class Alu:
    def __init__(self):
        self.act = [
            lambda a, b: a & b,  # 0  AND
            lambda a, b: ~(a & b),  # 1  NAND
            lambda a, b: ~(a | b),  # 2  NOR
            lambda a, b: a | b,  # 3  OR
            lambda a, b: a ^ b,  # 4  XOR
            lambda a, b: ~(a ^ b),  # 5  XNOR
            lambda a, b, cin=0: a + b + cin,  # 6  ADD
            lambda a, b: a - b,  # 7  SUB
            lambda a, b: a << (b & 15),  # 8  SHL
            lambda a, b: a >> (b & 15),  # 9  SHR
            lambda a, b: (a << (b & 15)) | (a >> (16 - (b & 15))),  # 10 ROL
            lambda a, b: (a >> (b & 15)) | (a << (16 - (b & 15))),  # 11 ROR
            lambda a, b: s16(a) >> (b & 15),  # 12 SRA
            lambda a, b: int(a == b),  # 13 SEQ
            lambda a, b: int(s16(a) < s16(b)),  # 14 SLT
            lambda a, b: int(a < b),  # 15 SLTU
            lambda a, b: a * b,  # 16 MUL
            lambda a, b: (s16(a) * s16(b)) >> 16,  # 17 MULH
            lambda a, b: (a * b) >> 16,  # 18 MLHU
            lambda a, b: a + 1,  # 19 INC
            lambda a, b: a - 1,  # 20 DEC
            lambda a, b: ~a,  # 21 NOT
            lambda a, b: -a,  # 22 NEG
            lambda a, b: self.clz(a),  # 23 CLZ
        ]

    def run(self, op, a, b=0, cin=0):
        return (
            self.act[op](a & M, b & M) & M
            if op != 6
            else self.act[op](a & M, b & M, cin & M) & M
        )

    def clz(self, a):
        return 16 - (a & M).bit_length()


class marc16:
    def __init__(self) -> None:
        self.bus = Bus(1 << 16)
        self.sys = Bus(1 << 8)

        self.clk = 0
        self.cycles = 0

        self.pc = Reg(self.sys, 0)
        self.ksp = Reg(self.sys, 1)
        self.usp = Reg(self.bus, 0xFF0C)

        self.irq_mask = Reg(self.bus, 0xFF04)
        self.irq_pend = Reg(self.bus, 0xFF05)

        self.ipc = Reg(self.bus, 0xFF06)

        self.ie = Bit(self.bus, 0xFF07, 0, 1)
        self.mode = Bit(self.bus, 0xFF07, 1, 1)
        self.pmode = Bit(self.bus, 0xFF07, 2, 1)
        self.pie = Bit(self.bus, 0xFF07, 3, 1)
        self.double_fault = Bit(self.bus, 0xFF07, 8, 1)
        self.sp_mode = Bit(self.bus, 0xFF07, 9, 1)
        self.psp_mode = Bit(self.bus, 0xFF07, 10, 1)
        self.hw_vec_id = Bit(self.bus, 0xFF07, 4, 4)
        self.sys_vec_id = Bit(self.bus, 0xFF07, 11, 4)

        self.sp = Sp(self.sp_mode, self.usp, self.ksp)

        self.rgf = Rgf(self.sp)

        self.ifid = Reg(self.sys, 2)
        self.idex = Reg(self.sys, 3)
        self.exmem = Reg(self.sys, 4)
        self.memwb = Reg(self.sys, 5)

        self.op = Bit(self.sys, 6, 0, 3)
        self.subop = Bit(self.sys, 6, 3, 5)
        self.rd = Bit(self.sys, 6, 8, 4)
        self.rs = Bit(self.sys, 6, 12, 4)
        self.offset4 = Bit(self.sys, 7, 0, 4)
        self.imm8 = Bit(self.sys, 7, 4, 8)
        self.imm12 = Bit(self.sys, 8, 0, 12)

        self.ALU = Alu()

        self.passif = Bit(self.sys, 9, 0, 1)
        self.passif.v = False

        self.IF = If(self.passif, self.pc, self.bus, self.ifid)
        self.ID = Id(
            self.ifid,
            self.idex,
        )
        self.EX = Ex(
            self.ifid, self.idex, self.exmem, self.ALU, self.rgf, self.pc, self.passif
        )
        self.MEM = Mem(self.bus, self.exmem)
        self.WB = Wb(self.rgf, self.memwb)

    def load_program(self, start, size, program):
        for i in range(size):
            self.bus[i + start] = program[i]

    def run(self):
        while True:
            self.WB.step()
            self.MEM.step()
            self.EX.step()
            self.ID.step()
            self.IF.step()


alu = Alu()

print(alu.act[0](1, 2))
