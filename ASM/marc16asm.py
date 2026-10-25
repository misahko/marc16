#!/usr/bin/env python3
"""
marc16asm.py - Асемблер для 16-бітної RISC архітектури MARC-16.
Підтримує вибір форматів виводу через прапорці:
  - verilog ($readmemh, за замовчуванням)
  - logisim (Logisim v3.0 hex words addressed)
  - bin (Raw binary little-endian)
  - lst (Текстовий лістинг для відладки)
"""

import argparse
import re
import sys

WORDS_PER_LINE = 16
ROM_SIZE = 4096

commands = {
    # RGF (група 000)
    "mov": (0b00000, 0b000),
    "swpb": (0b00001, 0b000),
    "zexb": (0b00010, 0b000),
    "sexb": (0b00011, 0b000),
    "movh": (0b00100, 0b000),
    "movl": (0b00101, 0b000),
    # ALU (група 001)
    "and": (0b00000, 0b001),
    "nand": (0b00001, 0b001),
    "nor": (0b00010, 0b001),
    "or": (0b00011, 0b001),
    "xor": (0b00100, 0b001),
    "xnor": (0b00101, 0b001),
    "add": (0b00110, 0b001),
    "sub": (0b00111, 0b001),
    "shl": (0b01000, 0b001),
    "shr": (0b01001, 0b001),
    "rol": (0b01010, 0b001),
    "ror": (0b01011, 0b001),
    "sra": (0b01100, 0b001),
    "seq": (0b01101, 0b001),
    "slt": (0b01110, 0b001),
    "sltu": (0b01111, 0b001),
    "mul": (0b10000, 0b001),
    "mulh": (0b10001, 0b001),
    "mlhu": (0b10010, 0b001),
    "inc": (0b10011, 0b001),
    "dec": (0b10100, 0b001),
    "not": (0b10101, 0b001),
    "neg": (0b10110, 0b001),
    "clz": (0b10111, 0b001),
    # COND (група 010)
    "jz": (0b0, 0b010),
    "jnz": (0b1, 0b010),
    # JMP (група 011)
    "jmp": (0b0, 0b011),
    "call": (0b1, 0b011),
    # IMM (група 100)
    "movi": (0b0, 0b100),
    "lui": (0b1, 0b100),
    # MEM (група 101)
    "push": (0b00000, 0b101),
    "pop": (0b00001, 0b101),
    "xchg": (0b00010, 0b101),
    # MEM-OFFSET (група 110): S_flag = 0 для ld, S_flag = 1 для st
    "ld": (0b0, 0b110),
    "st": (0b1, 0b110),
    # SYS (група 111)
    "ei": (0b00000, 0b111),
    "di": (0b00001, 0b111),
    "jr": (0b00010, 0b111),
    "callr": (0b00011, 0b111),
    "reti": (0b00100, 0b111),
    "scall": (0b00101, 0b111),
    "syscall": (0b00101, 0b111),
    "wfi": (0b00110, 0b111),
}

arguments = {
    "r0": 0b0000,
    "r1": 0b0001,
    "r2": 0b0010,
    "r3": 0b0011,
    "r4": 0b0100,
    "r5": 0b0101,
    "r6": 0b0110,
    "r7": 0b0111,
    "r8": 0b1000,
    "r9": 0b1001,
    "r10": 0b1010,
    "r11": 0b1011,
    "r12": 0b1100,
    "r13": 0b1101,
    "r14": 0b1110,
    "r15": 0b1111,
    "sp": 0b1111,
    "lr": 0b1110,
    "fp": 0b1000,
    "a0": 0b0001,
    "a1": 0b0010,
    "a2": 0b0011,
    "a3": 0b0100,
    "t0": 0b0000,
    "t1": 0b0101,
    "t2": 0b0110,
    "t3": 0b0111,
    "s0": 0b1000,
    "s1": 0b1001,
    "s2": 0b1010,
    "s3": 0b1011,
    "s4": 0b1100,
    "s5": 0b1101,
}


def parse_reg(reg_str):
    reg = reg_str.strip().lower()
    if reg in arguments:
        return arguments[reg]

    raise ValueError(f"Невідомий регістр: {reg_str}")


def parse_int(val_str):
    val_str = val_str.strip()
    return int(val_str, 0)


def parse_mem_operand(op_str):
    clean = op_str.strip()
    if clean.startswith("[") and clean.endswith("]"):
        clean = clean[1:-1].strip()

    parts = re.split(r"[\+,]", clean)
    rs = parts[0].strip()

    offset = parse_int(parts[1]) if len(parts) > 1 else 0
    return rs, offset


def expand_pseudo(mnemonic, args):
    op = mnemonic.lower()

    match op:
        case "ret":
            return [("jr", ["lr"])]

        case "clr":
            return [("xor", [args[0], args[0]])]

        case "nop":
            return [("mov", ["r0", "r0"])]

        case "syscall":
            return [("scall", [args[0]])]

        case "li16":
            rd, val = args[0], args[1]

            try:
                imm = parse_int(val)
                if 0 <= imm <= 0xFF:
                    return [("movi", [rd, str(imm)])]

                high = (imm >> 8) & 0xFF
                low = imm & 0xFF

                if low == 0:
                    return [
                        ("movi", [rd, "0"]),
                        ("lui", [rd, str(high)]),
                    ]

                return [
                    ("movi", [rd, str(low)]),
                    ("lui", [rd, str(high)]),
                ]
            except ValueError:
                return [("movi", [rd, f"low({val})"]), ("lui", [rd, f"high({val})"])]

    return [(op, args)]


def decode(mnemonic, args, addr, labels):
    op = mnemonic.lower()
    if op not in commands:
        raise ValueError(f"Невідома команда: {op}")

    subop, group = commands[op]
    command = 0

    if group == 0b000:
        rd = parse_reg(args[0])
        rs = parse_reg(args[1])
        command |= (rd << 12) | (rs << 8) | (subop << 3) | group

    elif group == 0b001:
        ra = parse_reg(args[0])
        rb = 0 if op in ("inc", "dec", "not", "neg", "clz") else parse_reg(args[1])
        command = (ra << 12) | (rb << 8) | (subop << 3) | group

    elif group == 0b010:
        rs = parse_reg(args[0])
        target = args[1].strip()
        offset = (
            (labels[target] - (addr + 1)) if target in labels else parse_int(target)
        )

        if not (-128 <= offset <= 127):
            raise ValueError(f"Зміщення для {op} ({offset}) виходить за межі 8 біт")

        command |= (rs << 12) | ((offset & 0xFF) << 4) | ((subop & 1) << 3) | group

    elif group == 0b011:
        target = args[0].strip()
        offset = (
            (labels[target] - (addr + 1)) if target in labels else parse_int(target)
        )

        if not (-2048 <= offset <= 2047):
            raise ValueError(f"Зміщення для {op} ({offset}) виходить за межі 12 біт")

        command |= ((offset & 0x0FFF) << 4) | ((subop & 1) << 3) | group

    elif group == 0b100:
        rd = parse_reg(args[0])
        val_str = args[1].strip()
        if val_str.startswith("high(") and val_str.endswith(")"):
            lbl = val_str[5:-1].strip()
            imm8 = (labels[lbl] >> 8) & 0xFF
        elif val_str.startswith("low(") and val_str.endswith(")"):
            lbl = val_str[4:-1].strip()
            imm8 = labels[lbl] & 0xFF
        elif val_str in labels:
            imm8 = labels[val_str] & 0xFF
        else:
            val = parse_int(val_str)
            if not (-128 <= val <= 255):
                raise ValueError(
                    f"Константа {val_str} для {op} виходить за межі 8 біт! Використовуйте li16."
                )
            imm8 = val & 0xFF
        h_flag = subop & 1
        command = (rd << 12) | (imm8 << 4) | (h_flag << 3) | group

    elif group == 0b101:
        rd = 0
        rs = 0
        if op == "push":
            rs = parse_reg(args[0])
            rd = 0
        elif op == "pop":
            rd = parse_reg(args[0])
            rs = 0
        elif op == "xchg":
            rd = parse_reg(args[0])
            rs_str, _ = parse_mem_operand(args[1])
            rs = parse_reg(rs_str)
        command = (rd << 12) | (rs << 8) | (subop << 3) | group

    elif group == 0b110:
        rd = parse_reg(args[0])
        rs_str, offset = parse_mem_operand(args[1])
        rs = parse_reg(rs_str)
        if not (0 <= offset <= 15):
            raise ValueError(
                f"Зміщення пам'яті {offset} повинно бути в діапазоні 0..15"
            )
        s_flag = subop & 1
        command = (
            (rd << 12) | (rs << 8) | ((offset & 0x0F) << 4) | (s_flag << 3) | group
        )

    elif group == 0b111:
        rs = 0
        if op in ("jr", "callr"):
            rs = parse_reg(args[0])
        elif op in ("scall", "syscall"):
            rs = parse_int(args[0]) & 0x0F
        command = (rs << 8) | (subop << 3) | group

    return [command]


def parse_line(line):
    """
    Очищає рядок від коментарів і розбирає мітки, мнемоніку та аргументи.
    """
    clean = re.sub(r"[;#].*$", "", line).strip()
    if not clean:
        return None, None, []

    label = None
    if ":" in clean:
        parts = clean.split(":", 1)
        label = parts[0].strip()
        clean = parts[1].strip()

    if not clean:
        return label, None, []

    # Виділяємо мнемоніку та аргументи
    tokens = clean.split(maxsplit=1)
    mnemonic = tokens[0]
    args = []
    if len(tokens) > 1:
        # Безпечний поділ за комою поза межами дужок [...]
        raw_args = tokens[1]
        cur = []
        in_b = False
        for ch in raw_args:
            if ch == "[":
                in_b = True
            elif ch == "]":
                in_b = False
            if ch == "," and not in_b:
                args.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
        if cur:
            args.append("".join(cur).strip())

    return label, mnemonic, args


def assemble(lines):
    labels = {}
    ir = []

    # PASS 1: Облік міток та розгортання псевдоінструкцій
    addr = 0
    for line in lines:
        lbl, mnem, args = parse_line(line)
        if lbl:
            labels[lbl] = addr

        if not mnem:
            continue

        if mnem.lower() == ".word":
            ir.append((addr, ".word", args, line.strip()))
            addr += 1
            continue

        expanded = expand_pseudo(mnem, args)
        for sub_mnem, sub_args in expanded:
            ir.append((addr, sub_mnem, sub_args, line.strip()))
            addr += 1

    labels["_end"] = addr

    # PASS 2: Генерація 16-бітного машинного коду та деталей
    program = []
    details = []
    for cur_addr, mnem, args, raw_line in ir:
        if mnem == ".word":
            val_str = args[0]
            val = labels[val_str] if val_str in labels else parse_int(val_str)
            word = val & 0xFFFF
            program.append(word)
            details.append((cur_addr, word, f".word {val_str}", raw_line))
        else:
            words = decode(mnem, args, cur_addr, labels)
            for w in words:
                program.append(w)
                arg_str = ", ".join(args)
                details.append((cur_addr, w, f"{mnem} {arg_str}".strip(), raw_line))

    return program, details, labels


def compile_file(
    input_file, output_file=None, fmt="verilog", rom_size=ROM_SIZE, write_lst=False
):
    with open(input_file, "r", encoding="utf-8") as file:
        content = file.read().splitlines()

    program, details, labels = assemble(content)

    if len(program) > rom_size:
        print(
            f"Попередження: розмір програми ({len(program)} слів) перевищує розмір ROM ({rom_size} слів)!"
        )
        actual_size = len(program)
    else:
        actual_size = rom_size

    # Визначення імені вихідного файлу за замовчуванням
    if not output_file:
        base_name = input_file.rsplit(".", 1)[0]
        ext_map = {"verilog": ".hex", "logisim": ".hex", "bin": ".bin", "lst": ".lst"}
        output_file = f"{base_name}{ext_map.get(fmt, '.hex')}"

    # 1. Формат Verilog ($readmemh) - за замовчуванням
    if fmt == "verilog":
        with open(output_file, "w", encoding="utf-8") as f:
            for w in program:
                f.write(f"{w:04x}\n")
        print(f"[{fmt.upper()}] Згенеровано {len(program)} слів -> {output_file}")

    # 2. Формат Logisim (v3.0 hex words addressed)
    elif fmt == "logisim":
        memory = program + [0] * (actual_size - len(program))
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("v3.0 hex words addressed\n")
            for addr in range(0, actual_size, WORDS_PER_LINE):
                row = memory[addr : addr + WORDS_PER_LINE]
                hex_values = " ".join(f"{v:04x}" for v in row)
                f.write(f"{addr:03x}: {hex_values}\n")
        print(f"[{fmt.upper()}] Згенеровано {actual_size} слів -> {output_file}")

    # 3. Формат Raw Binary (Little-Endian)
    elif fmt == "bin":
        with open(output_file, "wb") as f:
            for w in program:
                f.write(w.to_bytes(2, byteorder="little"))
        print(f"[{fmt.upper()}] Згенеровано {len(program) * 2} байт -> {output_file}")

    # 4. Формат Listing (.lst)
    elif fmt == "lst":
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(
                f"{'ADDR':<6} | {'HEX':<6} | {'BINARY (16-BIT)':<19} | {'DISASM':<20} | {'SOURCE'}\n"
            )
            f.write("-" * 75 + "\n")
            for addr, w, disasm, raw in details:
                bits = f"{w:016b}"
                bit_str = f"{bits[:4]} {bits[4:8]} {bits[8:12]} {bits[12:]}"
                f.write(
                    f"0x{addr:04X} | 0x{w:04X} | {bit_str} | {disasm:<20} | {raw}\n"
                )
        print(f"[{fmt.upper()}] Лістинг збережено -> {output_file}")

    # Додатковий запис .lst якщо увімкнено окремий прапорець
    if write_lst and fmt != "lst":
        lst_file = output_file.rsplit(".", 1)[0] + ".lst"
        with open(lst_file, "w", encoding="utf-8") as f:
            f.write(
                f"{'ADDR':<6} | {'HEX':<6} | {'BINARY (16-BIT)':<19} | {'DISASM':<20} | {'SOURCE'}\n"
            )
            f.write("-" * 75 + "\n")
            for addr, w, disasm, raw in details:
                bits = f"{w:016b}"
                bit_str = f"{bits[:4]} {bits[4:8]} {bits[8:12]} {bits[12:]}"
                f.write(
                    f"0x{addr:04X} | 0x{w:04X} | {bit_str} | {disasm:<20} | {raw}\n"
                )
        print(f"[LST] Супутній лістинг збережено -> {lst_file}")


def main():
    parser = argparse.ArgumentParser(
        description="marc16asm - Асемблер для процесора MARC-16"
    )
    parser.add_argument("input_file", help="Вхідний файл асемблерного коду (.asm)")
    parser.add_argument(
        "-o",
        "--output",
        dest="output_file",
        default=None,
        help="Шлях до вихідного файлу (за замовчуванням визначається за форматом)",
    )
    parser.add_argument(
        "-f",
        "--format",
        dest="format",
        choices=["verilog", "logisim", "bin", "lst"],
        default="verilog",
        help="Формат виводу: verilog ($readmemh, за замовчуванням), logisim, bin, lst",
    )
    parser.add_argument(
        "--lst",
        action="store_true",
        dest="write_lst",
        help="Додатково генерувати файл налагодження .lst поруч із основним",
    )
    parser.add_argument(
        "--rom-size",
        type=int,
        default=ROM_SIZE,
        dest="rom_size",
        help=f"Розмір ROM у словах (за замовчуванням: {ROM_SIZE})",
    )

    args = parser.parse_args()
    compile_file(
        input_file=args.input_file,
        output_file=args.output_file,
        fmt=args.format,
        rom_size=args.rom_size,
        write_lst=args.write_lst,
    )


if __name__ == "__main__":
    main()
