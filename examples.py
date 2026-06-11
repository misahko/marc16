#!/usr/bin/env python3
"""
Examples for the custom 16-bit processor emulator.

IMPORTANT NOTE about constants:
  Always use MOVH Rx 0x00 + MOVL Rx val for any constant.
  MOVL alone only writes the low byte and preserves the high byte,
  which causes bugs if the register previously held an address value.

Examples:
  1. Fibonacci sequence (first 10 numbers)
  2. Bubble sort (8 numbers)
  3. Factorial (iterative, n=7)
"""
import sys, math
sys.path.insert(0, '/home/claude')
from emulator import Assembler, HaltTrap

def run_example(name, source, show, patch_ram=None):
    print(f"\n{'='*52}\n  {name}\n{'='*52}")
    asm = Assembler()
    ram = asm.assemble(source)
    if asm.errors:
        for e in asm.errors: print("  ASM ERR:", e)
        return
    if patch_ram:
        patch_ram(ram)
    cpu = HaltTrap(ram=ram)
    cpu.run(max_cycles=500_000)
    show(cpu)
    print(f"  Cycles: {cpu.cycles}")


# ─────────────────────────────────────────────
# 1. Fibonacci
# R0=prev R1=curr R2=temp R3=counter R4=addr R5=limit
# Results stored at RAM[0x0100..0x0109]
# ─────────────────────────────────────────────
# .org 0x0040: 6 init instructions (0x40..0x45)
# loop: starts at 0x46

FIB_SOURCE = """
.org 0x0040
    MOVH R0 0x00
    MOVL R0 0
    MOVH R1 0x00
    MOVL R1 1
    MOVH R3 0x00
    MOVL R3 0
    MOVH R4 0x01
    MOVL R4 0x00
    MOVH R5 0x00
    MOVL R5 10

.org 0x004A
loop:
    STORE R1 R4
    MOVH  R2 0x00
    MOVL  R2 1
    ADD   R4 R2 R4
    ADD   R0 R1 R2
    MOV   R1 R0
    MOV   R2 R1
    MOVH  R2 0x00
    MOVL  R2 1
    ADD   R3 R2 R3
    MOVH  R6 0x00
    MOVL  R6 0x4A
    BLT   R3 R5 R6
    HALT
"""

def show_fib(cpu):
    nums = [cpu.ram[0x0100 + i] for i in range(10)]
    expected = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55]
    print(f"  Result:   {nums}")
    print(f"  Expected: {expected}")
    print(f"  {'✓ Correct' if nums == expected else '✗ Wrong'}")


# ─────────────────────────────────────────────
# 2. Bubble sort
# Array at RAM[0x0200..0x0207]
# .org pinned for precise jump targets
# ─────────────────────────────────────────────

SORT_SOURCE = """
; Bubble sort
; R0=base R1=arr[i] R2=arr[i+1] R3=i R4=pass R5=N R6=addr/scratch
; NOTE: always MOVH Rx 0x00 + MOVL Rx val for constants

.org 0x0040
    MOVH R0 0x02
    MOVL R0 0x00
    MOVH R5 0x00
    MOVL R5 8
    MOVH R4 0x00
    MOVL R4 0

.org 0x0046
outer:
    MOVH R3 0x00
    MOVL R3 0

.org 0x0048
inner:
    ADD  R0 R3 R6
    LOAD R6 R1
    MOVH R2 0x00
    MOVL R2 1
    ADD  R0 R3 R6
    ADD  R6 R2 R6
    LOAD R6 R2
    MOVH R6 0x00
    MOVL R6 0x58
    BLE  R1 R2 R6
    ADD  R0 R3 R6
    STORE R2 R6
    MOVH R2 0x00
    MOVL R2 1
    ADD  R6 R2 R6
    STORE R1 R6

.org 0x0058
no_swap:
    MOVH R2 0x00
    MOVL R2 1
    ADD  R3 R2 R3
    MOVH R6 0x00
    MOVL R6 1
    SUB  R5 R6 R6
    SUB  R6 R4 R6
    MOVH R2 0x00
    MOVL R2 0x48
    BLT  R3 R6 R2
    MOVH R2 0x00
    MOVL R2 1
    ADD  R4 R2 R4
    MOVH R6 0x00
    MOVL R6 1
    SUB  R5 R6 R6
    MOVH R2 0x00
    MOVL R2 0x46
    BLT  R4 R6 R2
    HALT
"""

DATA = [64, 34, 25, 12, 22, 11, 90, 47]

def patch_sort(ram):
    for i, v in enumerate(DATA):
        ram[0x0200 + i] = v

def show_sort(cpu):
    result = [cpu.ram[0x0200 + i] for i in range(8)]
    print(f"  Input:    {DATA}")
    print(f"  Result:   {result}")
    print(f"  Expected: {sorted(DATA)}")
    print(f"  {'✓ Correct' if result == sorted(DATA) else '✗ Wrong'}")


# ─────────────────────────────────────────────
# 3. Factorial (iterative)
# factorial(7) = 7! = 5040
# R0=n R1=result R2=counter R3=1(const)
# loop: multiply result by counter while counter <= n
# MUL writes to BANK2.R0, copy back with MOVB
# ─────────────────────────────────────────────
# .org 0x0040: 8 init instructions (0x40..0x47)
# loop: at 0x48

FACT_SOURCE = """
.org 0x0040
    MOVH R0 0x00
    MOVL R0 7
    MOVH R1 0x00
    MOVL R1 1
    MOVH R2 0x00
    MOVL R2 1
    MOVH R3 0x00
    MOVL R3 1

.org 0x0048
loop:
    MUL  R1 R2
    MOVB B2.R0 B0.R1
    ADD  R2 R3 R2
    MOVH R6 0x00
    MOVL R6 0x48
    BLE  R2 R0 R6
    HALT
"""

def show_fact(cpu):
    result = cpu.banks[0][1]
    expected = math.factorial(7)
    print(f"  factorial(7) = {result}")
    print(f"  Expected:      {expected}")
    print(f"  {'✓ Correct' if result == expected else '✗ Wrong'}")


# ─────────────────────────────────────────────
# Run all
# ─────────────────────────────────────────────
if __name__ == "__main__":
    run_example("1. Fibonacci sequence (first 10)", FIB_SOURCE, show_fib)
    run_example("2. Bubble sort (8 numbers)", SORT_SOURCE, show_sort, patch_sort)
    run_example("3. Factorial iterative (n=7)", FACT_SOURCE, show_fact)
    print()
