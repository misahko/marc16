# MARC-16 RISC ISA Specification

## Overview
The **MARC-16** (Minimalist Architecture for Real-time Computing) is a 16-bit reduced-instruction-set architecture designed for high hardware efficiency, FPGA deployment (specifically targeting the Sipeed Tang Nano 20K / Gowin GW2AR-18), and embedded Real-Time Operating Systems (RTOS). It features:
- **16-bit fixed-width** instructions, data bus, and address bus
- **16 general-purpose & dedicated registers** (`r0`–`r13` GPRs, `r14` as `lr`, `r15` as `sp`) plus a 16-bit `PC` and shadow `IPC`
- **64K-word (128 KB) flat unified address space** with a floating `_end` boundary separating static code/data from the dynamic heap and stack pool
- **8 orthogonal instruction groups** selected by primary opcode bits `[2:0]` (`000` to `111`)
- **45+ hardware & pseudo-instructions** covering register byte manipulations, ALU, single-cycle DSP multiplication, branches, atomic memory operations, offset loads/stores, and system control
- **RTOS hardware acceleration**: Single-cycle Count Leading Zeros (`clz`) for $O(1)$ priority scheduling, atomic memory swap (`xchg`) for mutexes and semaphores, hardware memory protection (`MPU`), and Banked Stack Pointers (`KSP`/`USP`)
- **Vectored Interrupt, Exception & Syscall Architecture**: 16 CPU exception / trap pointer slots at `0x0000–0x000F` (Reset, Illegal Instruction, Privilege Fault, MPU Fault), 16 hardware peripheral IRQ slots at `0x0010–0x001F` (SysTick, UART, GPIO, SPI, DMA, I2C, PWM), and 16 software trap (`syscall`) pointer slots at `0x0020–0x002F`, with hardware support for clean software nested interrupts
- **Memory-Mapped I/O (MMIO)** reserved at `0xFF00–0xFFFF` for the System Timer, Interrupt Controller, Memory Protection Unit, CPU state / USP window, UART, GPIO, SPI, I2C, DMA, and PWM

---

## Key Features
- High-throughput **5-stage instruction pipeline** (`IF` – `ID` – `EX` – `MEM` – `WB`) with ALU forwarding, 1-cycle load-use interlock, and 2-cycle branch penalty
- Compact 16-bit fixed-width encoding maximizing internal FPGA BSRAM code density
- Two-operand destructive ALU architecture (`Rd/A` is both destination and first source operand)
- Consistent register field alignment (`[15:12]` and `[11:8]`) eliminating decoder multiplexer overhead
- Native hardware `push`/`pop` and 4-bit offset addressing (`ld`/`st`) for C stack frames and structs
- Single-cycle 16x16 hardware multiplication (`mul`, `mulh`, `mlhu`) mapped to FPGA DSP blocks
- Hardware pointer vector tables enabling dynamic runtime ISR, exception, and syscall registration
- Two-level privilege model (Kernel / User) with MMIO isolation, MPU write-bounds checking, privileged-instruction traps, and `DOUBLE_FAULT` kernel panic detection
- **Banked Stack Architecture**: Dedicated physical `r15_kernel` (`KSP`) and `r15_user` (`USP`) with automatic hardware switching and a kernel context-switch window (`CPU_USP` at `0xFF0C`)

---

## Register Architecture

### General-Purpose & Dedicated Registers

| Register | ABI Name | Role / Description | Saver | Notes |
|:--------:|:--------:|:-------------------|:-----:|:------|
| `r0` | `t0` | Temporary / Scratch | Caller | General-purpose register (NOT hardwired zero); assembler scratch |
| `r1` | `a0` | Argument 0 / Return Value | Caller | Primary function argument & return result |
| `r2` | `a1` | Argument 1 / Return High | Caller | Secondary function argument or upper 16-bit return value |
| `r3` | `a2` | Argument 2 | Caller | Function argument 2 |
| `r4` | `a3` | Argument 3 | Caller | Function argument 3 (further arguments spill to stack) |
| `r5` | `t1` | Temporary 1 | Caller | Volatile scratch register |
| `r6` | `t2` | Temporary 2 | Caller | Volatile scratch register |
| `r7` | `t3` | Temporary 3 | Caller | Volatile scratch register |
| `r8` | `s0` | Saved Register 0 / Frame Pointer (`fp`) | Callee | Preserved across function calls; optional frame pointer |
| `r9` | `s1` | Saved Register 1 | Callee | Preserved across function calls |
| `r10` | `s2` | Saved Register 2 | Callee | Preserved across function calls |
| `r11` | `s3` | Saved Register 3 | Callee | Preserved across function calls |
| `r12` | `s4` | Saved Register 4 | Callee | Preserved across function calls |
| `r13` | `s5` | Saved Register 5 / Thread Pointer (`tp`) | Callee | Preserved across calls; may hold current RTOS TCB pointer |
| **`r14`** | **`lr`** | **Link Register** | Caller | Hardware return address register updated by `call` and `callr` |
| **`r15`** | **`sp`** | **Stack Pointer** | Callee | Hardware Banked Stack Pointer: `r15_kernel` (`KSP`) when `SP_MODE == 0`, `r15_user` (`USP`) when `SP_MODE == 1` (`0xFEFF` init for `KSP`) |

### Special Internal Control Registers
- **`PC`**: 16-bit Program Counter addressing 16-bit instruction words (`0x0000–0xFFFF`).
- **`IPC`**: 16-bit Interrupt Program Counter (shadow register latching the return address upon hardware IRQ, fault trap, or `syscall`; memory-mapped at `0xFF06` for RTOS context switching).
- **`IE`**: 1-bit global Interrupt Enable flag (`1` = external IRQs enabled, `0` = masked). Exposed in `CPU_STATUS[0]` (`0xFF07`).
- **`MODE`**: 1-bit current Privilege Mode (`0` = Kernel/Privileged, `1` = User/Unprivileged). Exposed in `CPU_STATUS[1]` (`0xFF07`).
- **`PMODE`**: 1-bit Previous Privilege Mode, latched automatically upon entering any IRQ, trap, or `syscall` and restored into `MODE` by `reti`. Exposed in `CPU_STATUS[2]` (`0xFF07`).
- **`PIE`**: 1-bit Previous Interrupt Enable flag, latched automatically from `IE` upon entering any IRQ, trap, or `syscall` and restored into `IE` by `reti`. Exposed in `CPU_STATUS[3]` (`0xFF07`).
- **`DOUBLE_FAULT`**: 1-bit hardware Kernel Panic flag, latched to `1` if a fault occurs while already in Kernel Mode (`MODE == 0`). Exposed in `CPU_STATUS[8]` (`0xFF07`).
- **`SP_MODE`**: 1-bit Stack Pointer Mode selector in `CPU_STATUS[9]` (`0` = `KSP` active as `r15`, `1` = `USP` active as `r15`). In Kernel Mode, writing `SP_MODE` switches which stack register is active.
- **`PSP_MODE`**: 1-bit Previous Stack Pointer Mode in `CPU_STATUS[10]`: latched from `SP_MODE` upon entering IRQ/trap/syscall, restored by `reti`.
- **`HW_VEC_ID`**: 4-bit active hardware peripheral interrupt line (`IRQ 0..15`). Exposed in `CPU_STATUS[7:4]` (`0xFF07`).
- **`SYS_VEC_ID`**: 4-bit active software syscall (`0..15`) or CPU exception (`1..3`). Exposed in `CPU_STATUS[14:11]` (`0xFF07`).
- **`KSP` (`r15_kernel`)**: 16-bit physical Kernel Stack Pointer.
- **`USP` (`r15_user`)**: 16-bit physical User Stack Pointer.

### Reset & Trap Entry Behavior
- **`PC`**: Hardware state machine fetches the 16-bit Reset Vector pointer from `RAM[0x0000]` and loads `PC <= RAM[0x0000]` (typically `0x0030`).
- **`r15` (`sp` / `KSP`)**: Initialized to `0xFEFF` (top of general RAM, immediately below the `0xFF00` MMIO window).
- **`USP`**: Uninitialized on reset (configured by the RTOS kernel via the `CPU_USP` window at `0xFF0C`, or by setting `SP_MODE = 1` and writing `r15`, before launching User tasks).
- **`IE`, `MODE`, `PMODE`, `PIE`, `DOUBLE_FAULT`, `SP_MODE`, `PSP_MODE`**: Cleared to `0` on reset (the CPU starts in **Kernel Mode** using `KSP` with interrupts disabled).
- **`r0`–`r14`**: Undefined on hardware reset (software startup code clears registers if required).

> **On the Banked `SP` (`r15`) Architecture:** MARC-16 features **Banked Stack Pointers** controlled via the system status register and exposed through an MMIO window:
> - Hardware duplicates `r15` into two distinct physical registers: `r15_kernel` (`KSP`) and `r15_user` (`USP`).
> - **Register-Controlled Stack Mode (`SP_MODE`)**: The active stack pointer mapped to `r15` is determined by `CPU_STATUS[9] (SP_MODE)`.
>   - `SP_MODE == 0`: `r15` operates on `KSP` (Kernel Stack).
>   - `SP_MODE == 1`: `r15` operates on `USP` (User Stack).
> - **Kernel-Driven Stack Switching & `CPU_USP` Window**: In Kernel Mode (`MODE == 0`), the OS can read or write `USP` directly in a single instruction via the **`CPU_USP` (`0xFF0C`)** MMIO window while remaining on `KSP`, or switch the active `r15` bank by writing `SP_MODE` in `CPU_STATUS` (`0xFF07`) to manipulate the User Stack with native `r15` instructions (`push`, `pop`, `mov r15, rX`, `mov rX, r15`). Writes to `CPU_STATUS` are **hardware-serialized** (pipeline flush), so the new `SP_MODE` takes effect immediately for the very next instruction.
> - **User Mode Lock**: In User Mode (`MODE == 1`), `SP_MODE` is locked to `1` (`USP`), and user code cannot access or modify `CPU_STATUS` or `CPU_USP`.
> - **Automatic Trap Banking**: Entering any IRQ, trap, or `syscall` latches `PSP_MODE <= SP_MODE` and sets `SP_MODE <= 0`, guaranteeing that handlers always execute on `KSP`. Executing `reti` restores `SP_MODE <= PSP_MODE`.
> - Both stacks follow a **full-descending, pre-decrement** convention (`push Rs` performs `RAM[--SP] = Rs`; `pop Rd` performs `Rd = RAM[SP++]`). Initializing `KSP` at `0xFEFF` prevents collision with MMIO (`0xFF00–0xFFFF`).

> **Note on `r0` and `r14 (lr)`:** In MARC-16, `r0` is a standard read/write general-purpose register, not a hardwired zero. Register **`r14` (`lr`)** is the dedicated hardware Link Register automatically written by `call` and `callr`. Leaf functions can return in a single cycle via `jr r14` (`ret`), while non-leaf functions save `r14` onto the stack via `push r14`.

---

## Memory Map

MARC-16 employs a **Unified Flat Memory Model** across its 16-bit word address space (`0x0000–0xFFFF`). There is no rigid static partition between code and data RAM; instead, the linker exports the `_end` symbol immediately after the program's static sections, allowing the dynamic heap and stack to utilize 100% of remaining memory.

```text
Address      Size     Usage & Dynamic Growth Behavior
0xFFFF +------------+  --------------------------------------------------
       | MMIO / I/O |  256 words: TIMER, IRQ_CTRL, MPU, UART, GPIO, SPI, I2C, DMA, PWM (0xFF00..0xFFFF)
0xFF00 +------------+  --------------------------------------------------
       |   STACK    |  Stack top: SP (r15) initialized to 0xFEFF
       |     │      |  Stack grows DOWNWARD: push rX, local stack frames
       |     ▼      |  
       |            |  ══════════════════════════════════════════════════
       |    FREE    |  DYNAMIC UNIFIED MEMORY POOL
       |   MEMORY   |  Shared 100% between Heap and Stack!
       |    POOL    |  Collision check: (heap_ptr >= SP) -> Out of Memory
       |            |  ══════════════════════════════════════════════════
       |     ▲      |  
       |     │      |  Heap grows UPWARD from _end label: malloc(), buffers
       |    HEAP    |  
 _end  + - - - - - -+  <── FLOATING BOUNDARY (set by linker at build time)
       | DATA (.data|  
       |   & .bss)  |  Initialized & zero-initialized global/static variables
       +------------+  
       |    CODE    |  
       |  (.text)   |  Executable machine instructions (starts at 0x0030)
0x0030 +------------+  --------------------------------------------------
       |  SYSCALL   |  16 words: Pointer table for syscall 0..15 handlers
0x0020 +------------+  --------------------------------------------------
       |   HW IRQ   |  16 words: Peripheral IRQ 0..15 (Timer, UART, GPIO, SPI, DMA...)
0x0010 +------------+  --------------------------------------------------
       | CPU TRAPS  |  16 words: CPU Exceptions (0=Reset, 1=Illegal Inst, 2=Privilege, 3=MPU...)
0x0000 +------------+  --------------------------------------------------

```

| Address Range | Size | Usage |
| --- | --- | --- |
| `0x0000–0x000F` | 16 words | **CPU System Exception Vector Table** (Reset, Illegal Instruction, Privilege, MPU) |
| `0x0010–0x001F` | 16 words | **Hardware Peripheral IRQ Table** (`IRQ 0..15` target handler addresses) |
| `0x0020–0x002F` | 16 words | **Software Syscall Vector Table** (`syscall 0..15` target handler addresses) |
| `0x0030–_end` | Variable | **Program Code (`.text`) & Static Data (`.data`, `.bss`)** |
| `_end–0xFEFF` | Variable | **Dynamic Free Memory Pool** (Heap growing upward, Stack `r15` growing downward) |
| `0xFF00–0xFFFF` | 256 words | **Reserved MMIO Peripheral Space** (`mem_addr[15:8] == 8'hFF`) |

---

## Exception, Interrupt & Syscall Vector Tables

Unlike architectures that store jump instructions in their vector table, MARC-16 uses **Pointer Vector Tables** storing raw 16-bit target handler addresses. The vector space is strictly partitioned into **CPU Synchronous Exceptions**, **Maskable Peripheral Interrupts (IRQs)**, and **Software Syscalls**:

### 1. CPU System Exception Table (`0x0000–0x000F`)
Exceptions are synchronous events triggered directly by the CPU pipeline during instruction decode or execution. They **cannot be masked** by `IE` or `IRQ_MASK`, because an illegal instruction, privilege violation, or out-of-bounds memory access cannot safely resume execution without OS intervention.

| Vector | RAM Address | Trap Source | Description |
|:---:|:---:|:---|:---|
| **Vector 0** | `0x0000` | **Reset** | Initial CPU boot entry point (default `0x0030`) |
| **Vector 1** | `0x0001` | **Illegal Instruction** | Undefined opcode `[2:0]`, invalid `op5` selector, or malformed instruction encoding |
| **Vector 2** | `0x0002` | **Privilege Fault** | Attempt to execute `ei`, `di`, `reti`, `wfi` in User Mode (`MODE == 1`) |
| **Vector 3** | `0x0003` | **MPU / MMIO Fault** | User Mode PC out of bounds, RAM write violation, or MMIO window access (`0xFF00–0xFFFF`) |
| **Vectors 4–15** | `0x0004–0x000F` | *Reserved* | Reserved for future CPU system traps |

> **Exception Entry Behavior:**
> When an exception occurs, hardware performs:
> - $IPC \leftarrow \text{faulting\textunderscore{}instruction\textunderscore{}PC}$ (preserves the exact offending instruction address for diagnostics)
> - $PMODE \leftarrow \text{MODE}, \quad PIE \leftarrow \text{IE}, \quad \text{PSP\textunderscore{}MODE} \leftarrow \text{SP\textunderscore{}MODE}$
> - $\text{MODE} \leftarrow 0 \text{ (Kernel)}, \quad \text{IE} \leftarrow 0, \quad \text{SP\textunderscore{}MODE} \leftarrow 0 \text{ (KSP)}$
> - $\text{SYS\textunderscore{}VEC\textunderscore{}ID} \leftarrow \text{exc\textunderscore{}id} \quad (\text{stored in } \text{CPU\textunderscore{}STATUS}[14:11])$
> - If the CPU was already in Kernel Mode (`MODE == 0`), hardware sets `DOUBLE_FAULT <= 1` in `CPU_STATUS[8]` (Kernel Panic).
> - $\text{PC} \leftarrow \text{RAM}[0x0000 + \text{exc\textunderscore{}id}]$

### 2. Hardware Peripheral IRQ Table (`0x0010–0x001F`)
Peripheral interrupts are asynchronous signals from on-chip peripherals. **100% of these lines are maskable** via `IRQ_MASK[15:0]` and the global `IE` flag:

| IRQ Line | RAM Address | Mask Bit | Peripheral Source | Description |
|:---:|:---:|:---:|:---|:---|
| **IRQ 0** | `0x0010` | `IRQ_MASK[0]` | **SysTick Timer** | RTOS system timer tick (`TIMER_CTRL[1]`) |
| **IRQ 1** | `0x0011` | `IRQ_MASK[1]` | **UART TX** | Transmit buffer empty (`UART_CTRL[1]`) |
| **IRQ 2** | `0x0012` | `IRQ_MASK[2]` | **UART RX** | Incoming byte received (`UART_CTRL[0]`) |
| **IRQ 3** | `0x0013` | `IRQ_MASK[3]` | **GPIO IRQ** | External input pin level change (`GPIO_IRQ_EN`) |
| **IRQ 4** | `0x0014` | `IRQ_MASK[4]` | **SPI IRQ** | SPI byte/word transfer complete (`SPI_CTRL[1]`) |
| **IRQ 5** | `0x0015` | `IRQ_MASK[5]` | **I2C IRQ** | I2C byte/transaction complete or bus event (`I2C_CTRL[5]`) |
| **IRQ 6** | `0x0016` | `IRQ_MASK[6]` | **DMA IRQ** | DMA block transfer complete or error (`ERR_MPU` / `ERR_ADDR`) (`DMA_CTRL[1]`) |
| **IRQ 7** | `0x0017` | `IRQ_MASK[7]` | **PWM IRQ** | PWM cycle period match (`PWM_CTRL`) |
| **IRQs 8–15** | `0x0018–0x001F` | `IRQ_MASK[15:8]` | *Reserved / Custom* | Free user/custom FPGA peripheral interrupt slots |

> **IRQ Entry Behavior:**
> When an unmasked IRQ triggers (`IE == 1 && (IRQ_PEND & IRQ_MASK) != 0`):
> - $IPC \leftarrow \text{next\textunderscore{}instruction\textunderscore{}PC}$ (address to resume after interrupt returns)
> - $PMODE \leftarrow \text{MODE}, \quad PIE \leftarrow \text{IE}, \quad \text{PSP\textunderscore{}MODE} \leftarrow \text{SP\textunderscore{}MODE}$
> - $\text{MODE} \leftarrow 0 \text{ (Kernel)}, \quad \text{IE} \leftarrow 0, \quad \text{SP\textunderscore{}MODE} \leftarrow 0 \text{ (KSP)}$
> - $\text{HW\textunderscore{}VEC\textunderscore{}ID} \leftarrow \text{irq\textunderscore{}id} \quad (\text{stored in } \text{CPU\textunderscore{}STATUS}[7:4])$
> - $\text{PC} \leftarrow \text{RAM}[0x0010 + \text{irq\textunderscore{}id}]$

### 3. Software Syscall Table (`0x0020–0x002F`)

Executing `syscall imm4` (`imm4` = `0..15`) atomically performs:
- $IPC \leftarrow \text{PC} + 1$
- $PMODE \leftarrow \text{MODE}, \quad PIE \leftarrow \text{IE}$
- $\text{PSP\textunderscore{}MODE} \leftarrow \text{SP\textunderscore{}MODE}, \quad \text{SP\textunderscore{}MODE} \leftarrow 0 \text{ (KSP)}$
- $\text{MODE} \leftarrow 0 \text{ (Kernel)}, \quad \text{IE} \leftarrow 0$
- $\text{SYS\textunderscore{}VEC\textunderscore{}ID} \leftarrow \text{imm4} \quad (\text{stored in } \text{CPU\textunderscore{}STATUS}[14:11])$
and fetches the handler address from `RAM[0x0020 + imm4]` in a single BRAM cycle.

### Return Mechanism (`reti`)

Executing `reti` (Kernel Mode only) atomically restores processor state:
- $\text{PC} \leftarrow \text{IPC}$
- $\text{MODE} \leftarrow \text{PMODE}$
- $\text{IE} \leftarrow \text{PIE}$
- $\text{SP\textunderscore{}MODE} \leftarrow \text{PSP\textunderscore{}MODE}$

Attempting to execute `reti` while in User Mode triggers **Vector 2 (`Privilege Fault`)**.



---

## Instruction Groups

Every instruction is 16 bits wide, with bits `[2:0]` selecting one of the 8 hardware instruction groups:

| Group (`[2:0]`) | Group Name | Description |
|:---:|:---:|:---|
| `000` | **RGF** | Register-to-register moves, byte swaps, and byte extensions |
| `001` | **ALU** | Two-operand arithmetic, logic, shifts, DSP multiply, unary ops, and `clz` |
| `010` | **COND** | Conditional PC-relative branches (`jz`, `jnz`) |
| `011` | **JMP** | Unconditional jumps and subroutine calls (`jmp`, `call`) |
| `100` | **IMM** | 8-bit immediate loading (`movi`, `lui`) |
| `101` | **MEM** | Hardware stack `push`/`pop` and atomic `xchg` |
| `110` | **MEM-OFS** | Base-register + 4-bit unsigned offset loads and stores (`ld`, `st`) |
| `111` | **SYS** | Interrupt control, indirect jumps/calls (`jr`, `callr`), `reti`, `syscall`, `wfi` |

---

## MARC-16 Instruction Format Field Layouts

### Group `000`: RGF (Register & Byte Operations)

```text
 15  14  13  12  11  10   9   8   7   6   5   4   3   2   1   0
┌───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐
│      Rd       │      Rs       │      op5          │ 0 │ 0 │ 0 │
└───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┘

```

* **`[15:12]`** `Rd` (Destination register `r0`–`r15`)
* **`[11:8]`** `Rs` (Source register `r0`–`r15`)
* **`[7:3]`** `op5` (5-bit RGF sub-opcode)
* **`[2:0]`** `000`

### Group `001`: ALU (Arithmetic, Logic, Shifts, Multiply & Unary)

```text
 15  14  13  12  11  10   9   8   7   6   5   4   3   2   1   0
┌───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐
│       A       │   B / 0000    │      op5          │ 0 │ 0 │ 1 │
└───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┘

```

* **`[15:12]`** `A` (Destination & first source register `r0`–`r15`)
* **`[11:8]`** `B` (Second source register `r0`–`r15`; set to `0000` for unary instructions `inc`, `dec`, `not`, `neg`, `clz`)
* **`[7:3]`** `op5` (5-bit ALU operation selector)
* **`[2:0]`** `001`

### Group `010`: COND (Conditional Branches)

```text
 15  14  13  12  11  10   9   8   7   6   5   4   3   2   1   0
┌───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐
│      Rs       │        imm8 (signed)          │ C │ 0 │ 1 │ 0 │
└───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┘

```

* **`[15:12]`** `Rs` (Register tested against zero)
* **`[11:4]`** `imm8` (8-bit signed PC-relative word offset: `-128` to `+127` words)
* **`[3]`** `C` (Condition flag: `0` = `jz`, `1` = `jnz`)
* **`[2:0]`** `010`

### Group `011`: JMP (Direct Jumps & Subroutine Calls)

```text
 15  14  13  12  11  10   9   8   7   6   5   4   3   2   1   0
┌───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐
│                  imm12                        │ L │ 0 │ 1 │ 1 │
└───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┘

```

* **`[15:4]`** `imm12` (12-bit signed PC-relative word offset: `-2048` to `+2047` words; farther targets require `li16` + `jr`/`callr`)
* **`[3]`** `L` (Link flag: `0` = `jmp`, `1` = `call` storing `call_instruction_PC + 1` into `r14` / `lr`)
* **`[2:0]`** `011`

### Group `100`: IMM (Immediate Constant Loads)

```text
 15  14  13  12  11  10   9   8   7   6   5   4   3   2   1   0
┌───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐
│      Rd       │             imm8              │ H │ 1 │ 0 │ 0 │
└───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┘

```

* **`[15:12]`** `Rd` (Destination register `r0`–`r15`)
* **`[11:4]`** `imm8` (8-bit immediate byte `0x00–0xFF`)
* **`[3]`** `H` (Half selector: `0` = `movi` low byte zero-extended, `1` = `lui` high byte)
* **`[2:0]`** `100`

### Group `101`: MEM (Stack & Atomic Exchange)

```text
 15  14  13  12  11  10   9   8   7   6   5   4   3   2   1   0
┌───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐
│  Rd / 0000    │  Rs / 0000    │      op5          │ 1 │ 0 │ 1 │
└───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┘
```

* **`[15:12]`** `Rd` (Data register for `pop`, `xchg`; `0000` for `push`)
* **`[11:8]`** `Rs` (Address pointer register for `xchg`; source register for `push`; `0000` for `pop`)
* **`[7:3]`** `op5` (5-bit memory sub-opcode: `00000` = `push`, `00001` = `pop`, `00010` = `xchg`)
* **`[2:0]`** `101`

### Group `110`: MEM-OFFSET (Base + Offset Load/Store)

```text
 15  14  13  12  11  10   9   8   7   6   5   4   3   2   1   0
┌───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐
│      Rd       │      Rs       │    offset4    │ S │ 1 │ 1 │ 0 │
└───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┘

```

* **`[15:12]`** `Rd` (Data register: destination for `ld`, source data for `st`)
* **`[11:8]`** `Rs` (Base address register, e.g., `sp` (`r15`) or struct pointer)
* **`[7:4]`** `offset4` (4-bit unsigned word offset: `0` to `15`)
* **`[3]`** `S` (Store flag: `0` = `ld`, `1` = `st`)
* **`[2:0]`** `110`

### Group `111`: SYS (System Control, Indirect Jumps & Traps)

```text
 15  14  13  12  11  10   9   8   7   6   5   4   3   2   1   0
┌───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐
│     0000      │ Rs/imm4/0000  │      op5          │ 1 │ 1 │ 1 │
└───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┘

```

* **`[15:12]`** `0000` (Reserved, must be zero)
* **`[11:8]`** `Rs` (Target register for `jr`/`callr`), `imm4` (Service ID `0..15` for `syscall`), or `0000` (for `ei`, `di`, `reti`, `wfi`)
* **`[7:3]`** `op5` (5-bit system operation code)
* **`[2:0]`** `111`

---

## Instruction Set Reference

### Group `000`: RGF Instructions

| Mnemonic | Syntax | Description |
| --- | --- | --- |
| **MOV** | `mov Rd, Rs` | `Rd ← Rs` (Copy register `Rs` to `Rd`) |
| **SWPB** | `swpb Rd, Rs` | `Rd ← {Rs[7:0], Rs[15:8]}` (Swap upper and lower bytes) |
| **ZEXB** | `zexb Rd, Rs` | `Rd ← {8'h00, Rs[7:0]}` (Zero-extend low byte to 16 bits) |
| **SEXB** | `sexb Rd, Rs` | `Rd ← {{8{Rs[7]}}, Rs[7:0]}` (Sign-extend low byte to 16 bits) |
| **MOVH** | `movh Rd, Rs` | `Rd ← {Rs[7:0], Rd[7:0]}` (Pack `Rs[7:0]` into upper byte of `Rd`, keeping `Rd[7:0]`) |
| **MOVL** | `movl Rd, Rs` | `Rd ← {Rd[15:8], Rs[7:0]}` (Pack `Rs[7:0]` into lower byte of `Rd`, keeping `Rd[15:8]`) |

### Group `001`: ALU Instructions

| Mnemonic | Syntax | Description |
| --- | --- | --- |
| **AND** | `and A, B` | `A ← A & B` (Bitwise AND) |
| **NAND** | `nand A, B` | `A ← ~(A & B)` (Bitwise NAND) |
| **NOR** | `nor A, B` | `A ← ~(A or B)` (Bitwise NOR) |
| **OR** | `or A, B` | `A ← A or B` (Bitwise OR) |
| **XOR** | `xor A, B` | `A ← A ^ B` (Bitwise XOR) |
| **XNOR** | `xnor A, B` | `A ← ~(A ^ B)` (Bitwise XNOR) |
| **ADD** | `add A, B` | `A ← A + B` (16-bit addition) |
| **SUB** | `sub A, B` | `A ← A - B` (16-bit subtraction) |
| **SHL** | `shl A, B` | `A ← A << B[3:0]` (Logical left shift by 0..15 bits) |
| **SHR** | `shr A, B` | `A ← A >> B[3:0]` (Logical right shift by 0..15 bits) |
| **ROL** | `rol A, B` | `A ← (A << B[3:0]) or (A >> (16 - B[3:0]))` |
| **ROR** | `ror A, B` | `A ← (A >> B[3:0]) or (A << (16 - B[3:0]))` |
| **SRA** | `sra A, B` | `A ← $signed(A) >>> B[3:0]` (Arithmetic sign-preserving right shift) |
| **SEQ** | `seq A, B` | `A ← (A == B) ? 1 : 0` (Set 1 if equal, else 0) |
| **SLT** | `slt A, B` | `A ← ($signed(A) < $signed(B)) ? 1 : 0` (Set 1 if signed less-than) |
| **SLTU** | `sltu A, B` | `A ← (A < B) ? 1 : 0` (Set 1 if unsigned less-than) |
| **MUL** | `mul A, B` | `A ← (A * B)[15:0]` (Single-cycle lower 16-bit product via DSP) |
| **MULH** | `mulh A, B` | `A ← ($signed(A) * $signed(B))[31:16]` (Single-cycle signed upper 16-bit product) |
| **MLHU** | `mlhu A, B` | `A ← (A * B)[31:16]` (Single-cycle unsigned upper 16-bit product) |
| **INC** | `inc A` | `A ← A + 1` (Increment register by 1) |
| **DEC** | `dec A` | `A ← A - 1` (Decrement register by 1) |
| **NOT** | `not A` | `A ← ~A` (Bitwise one's complement inversion) |
| **NEG** | `neg A` | `A ← -A` (Two's complement arithmetic negation) |
| **CLZ** | `clz A` | `A ← CountLeadingZeros(A)` (Returns `0..16`; $O(1)$ RTOS priority finder) |

### Group `010`: COND Instructions

| Mnemonic | Syntax | Description |
| --- | --- | --- |
| **JZ** | `jz Rs, label` | `if (Rs == 0) PC ← PC + 1 + sext(imm8)` (Branch if zero) |
| **JNZ** | `jnz Rs, label` | `if (Rs != 0) PC ← PC + 1 + sext(imm8)` (Branch if non-zero) |

### Group `011`: JMP Instructions

| Mnemonic | Syntax | Description |
| --- | --- | --- |
| **JMP** | `jmp target` | `PC ← PC + 1 + sext(imm12)` (Unconditional jump) |
| **CALL** | `call target` | `r14 (lr) ← PC + 1; PC ← PC + 1 + sext(imm12)` (Subroutine call saving return address in `r14`) |

### Group `100`: IMM Instructions

| Mnemonic | Syntax | Description |
| --- | --- | --- |
| **MOVI** | `movi Rd, imm8` | `Rd ← {8'h00, imm8}` (Load 8-bit unsigned immediate into `Rd`) |
| **LUI** | `lui Rd, imm8` | `Rd ← {imm8, Rd[7:0]}` (Load 8-bit immediate into upper byte, preserving low byte) |

### Group `101`: MEM Instructions

| Mnemonic | Syntax | Description |
|:---|:---|:---|
| **PUSH** | `push Rs` | `r15 (sp) ← r15 - 1; RAM[r15] ← Rs` (Pre-decrement push onto stack) |
| **POP** | `pop Rd` | `Rd ← RAM[r15]; r15 (sp) ← r15 + 1` (Post-increment pop from stack) |
| **XCHG** | `xchg Rd, [Rs]` | `RAM[Rs], Rd = Rd, RAM[Rs]` (Atomic memory-register swap) |

### Group `110`: MEM-OFFSET Instructions

| Mnemonic | Syntax | Description |
| --- | --- | --- |
| **LD** | `ld Rd, [Rs + imm4]` | `Rd ← RAM[Rs + imm4]` (Load word from base `Rs` + unsigned offset `0..15`) |
| **ST** | `st Rd, [Rs + imm4]` | `RAM[Rs + imm4] ← Rd` (Store word `Rd` to base `Rs` + unsigned offset `0..15`) |

### Group `111`: SYS Instructions

| Mnemonic | Syntax | Description |
| --- | --- | --- |
| **EI** | `ei` | `IE ← 1` (Enable hardware interrupts globally; **Kernel Mode only**) |
| **DI** | `di` | `IE ← 0` (Disable hardware interrupts globally; **Kernel Mode only**) |
| **JR** | `jr Rs` | `PC ← Rs` (Unconditional indirect jump to address in `Rs`) |
| **CALLR** | `callr Rs` | `r14 (lr) ← call_inst_PC + 1; PC ← Rs` (Indirect subroutine call saving return in `r14`) |
| **RETI** | `reti` | `PC ← IPC; MODE ← PMODE; IE ← PIE; SP_MODE ← PSP_MODE` (Return from interrupt or trap; **Kernel Mode only**) |
| **SYSCALL** | `syscall imm4` | `IPC ← PC + 1; PMODE ← MODE; PIE ← IE; PSP_MODE ← SP_MODE; MODE ← 0; IE ← 0; SP_MODE ← 0; PC ← RAM[0x0020 + imm4]` (Invoke OS service `0..15`) |
| **WFI** | `wfi` | Wait For Interrupt (**Kernel Mode only**; halts core clock until `(IRQ_PEND & IRQ_MASK) != 0`; vectors to ISR if `IE == 1`, or resumes at `PC + 1` without vectoring if `IE == 0`) |

> **`WFI` (Wait For Interrupt) Execution Rules & Wake-Up Behavior:**
> The `wfi` instruction suspends the core clock until an unmasked hardware interrupt becomes pending (`(IRQ_PEND & IRQ_MASK) != 0`), regardless of the global `IE` flag:
> - **User Mode (`MODE == 1`):** Execution is blocked by the decoder, immediately triggering **Vector 2 (`Privilege Fault`)**.
> - **Kernel Mode with `IE == 1`:** The core halts clocking until `(IRQ_PEND & IRQ_MASK) != 0`. Upon wake-up, the CPU immediately services the highest-priority pending interrupt and jumps to its vector (`RAM[0x0010 + irq_id]`) with `IPC <= PC_of_wfi + 1`.
> - **Kernel Mode with `IE == 0`:** The core halts clocking until `(IRQ_PEND & IRQ_MASK) != 0`. Upon wake-up, because global interrupts are masked (`IE == 0`), the CPU **does not jump to the interrupt vector**; instead, it simply resumes sequential execution at the instruction immediately following `wfi` (`PC + 1`). This enables race-free kernel idle loops (`di` → check scheduler queue → `wfi` → `ei`) and low-power polling of `IRQ_PEND`.

> **Illegal Instruction Fault (Vector 1) Handling:**
> Any instruction encoding with an unmapped sub-opcode `op5` (e.g. RGF `op5 > 5`, ALU `op5 >= 24`, MEM `op5 > 2`, SYS `op5 > 6`) or violating fixed reserved fields (such as non-zero bits `[15:12]` in `SYS` instructions or non-zero bits `[11:8]` in unary ALU instructions) is intercepted during the `ID` stage, halts instruction retirement, preserves the address in `IPC`, and triggers **Vector 1 (`Illegal Instruction Fault`)**.


---

## Instruction Identification Table

| Mnemonic | Group | Opcode `[2:0]` | Bits `[15:12]` | Bits `[11:8]` | Bits `[7:3]` (`op5` / `imm`) | Operation Summary |
| --- | --- | --- | --- | --- | --- | --- |
| **RGF (`000`)** |  |  |  |  |  |  |
| `MOV` | RGF | `000` | `Rd` | `Rs` | `00000` | `Rd = Rs` |
| `SWPB` | RGF | `000` | `Rd` | `Rs` | `00001` | `Rd = {Rs[7:0], Rs[15:8]}` |
| `ZEXB` | RGF | `000` | `Rd` | `Rs` | `00010` | `Rd = {8'h00, Rs[7:0]}` |
| `SEXB` | RGF | `000` | `Rd` | `Rs` | `00011` | `Rd = {{8{Rs[7]}}, Rs[7:0]}` |
| `MOVH` | RGF | `000` | `Rd` | `Rs` | `00100` | `Rd = {Rs[7:0], Rd[7:0]}` |
| `MOVL` | RGF | `000` | `Rd` | `Rs` | `00101` | `Rd = {Rd[15:8], Rs[7:0]}` |
| **ALU (`001`)** |  |  |  |  |  |  |
| `AND` | ALU | `001` | `A` | `B` | `00000` | `A = A & B` |
| `NAND` | ALU | `001` | `A` | `B` | `00001` | `A = ~(A & B)` |
| `NOR` | ALU | `001` | `A` | `B` | `00010` | `A = ~(A \| B)` |
| `OR` | ALU | `001` | `A` | `B` | `00011` | `A = A \| B` |
| `XOR` | ALU | `001` | `A` | `B` | `00100` | `A = A ^ B` |
| `XNOR` | ALU | `001` | `A` | `B` | `00101` | `A = ~(A ^ B)` |
| `ADD` | ALU | `001` | `A` | `B` | `00110` | `A = A + B` |
| `SUB` | ALU | `001` | `A` | `B` | `00111` | `A = A - B` |
| `SHL` | ALU | `001` | `A` | `B` | `01000` | `A = A << B[3:0]` |
| `SHR` | ALU | `001` | `A` | `B` | `01001` | `A = A >> B[3:0]` |
| `ROL` | ALU | `001` | `A` | `B` | `01010` | `A = (A << B[3:0]) or (A >> (16 - B[3:0]))` |
| `ROR` | ALU | `001` | `A` | `B` | `01011` | `A = (A >> B[3:0]) or (A << (16 - B[3:0]))` |
| `SRA` | ALU | `001` | `A` | `B` | `01100` | `A = signed(A) >>> B[3:0]` |
| `SEQ` | ALU | `001` | `A` | `B` | `01101` | `A = (A == B) ? 1 : 0` |
| `SLT` | ALU | `001` | `A` | `B` | `01110` | `A = (signed(A) < signed(B)) ? 1 : 0` |
| `SLTU` | ALU | `001` | `A` | `B` | `01111` | `A = (A < B) ? 1 : 0` |
| `MUL` | ALU | `001` | `A` | `B` | `10000` | `A = (A * B)[15:0]` |
| `MULH` | ALU | `001` | `A` | `B` | `10010` | `A = (signed(A) * signed(B))[31:16]` |
| `MLHU` | ALU | `001` | `A` | `B` | `10010` | `A = (A * B)[31:16]` |
| `INC` | ALU | `001` | `A` | `0000` | `10011` | `A = A + 1` |
| `DEC` | ALU | `001` | `A` | `0000` | `10100` | `A = A - 1` |
| `NOT` | ALU | `001` | `A` | `0000` | `10101` | `A = ~A` |
| `NEG` | ALU | `001` | `A` | `0000` | `10110` | `A = -A` |
| `CLZ` | ALU | `001` | `A` | `0000` | `10111` | `A = CountLeadingZeros(A)` |
| **COND (`010`)** |  |  |  |  |  |  |
| `JZ` | COND | `010` | `Rs` | `imm8[7:4]` | `{imm8[3:0], 1'b0}` | Branch if `Rs == 0` |
| `JNZ` | COND | `010` | `Rs` | `imm8[7:4]` | `{imm8[3:0], 1'b1}` | Branch if `Rs != 0` |
| **JMP (`011`)** |  |  |  |  |  |  |
| `JMP` | JMP | `011` | `imm12[11:8]` | `imm12[7:4]` | `{imm12[3:0], 1'b0}` | `PC = PC + 1 + sext(imm12)` |
| `CALL` | JMP | `011` | `imm12[11:8]` | `imm12[7:4]` | `{imm12[3:0], 1'b1}` | `r14 (lr) = call_inst_PC + 1; PC = target` |
| **IMM (`100`)** |  |  |  |  |  |  |
| `MOVI` | IMM | `100` | `Rd` | `imm8[7:4]` | `{imm8[3:0], 1'b0}` | `Rd = {8'h00, imm8}` |
| `LUI` | IMM | `100` | `Rd` | `imm8[7:4]` | `{imm8[3:0], 1'b1}` | `Rd = {imm8, Rd[7:0]}` |
| **MEM (`101`)** |  |  |  |  |  |  |
| `PUSH` | MEM | `101` | `0000` | `Rs` | `00000` | `RAM[--r15] = Rs` |
| `POP` | MEM | `101` | `Rd` | `0000` | `00001` | `Rd = RAM[r15++]` |
| `XCHG` | MEM | `101` | `Rd` | `Rs` | `00010` | `RAM[Rs], Rd = Rd, RAM[Rs]` |
| **MEM-OFS (`110`)** |  |  |  |  |  |  |
| `LD` | MEM-OFS | `110` | `Rd` | `Rs` | `{offset4, 1'b0}` | `Rd = RAM[Rs + offset4]` |
| `ST` | MEM-OFS | `110` | `Rd` | `Rs` | `{offset4, 1'b1}` | `RAM[Rs + offset4] = Rd` |
| **SYS (`111`)** |  |  |  |  |  |  |
| `EI` | SYS | `111` | `0000` | `0000` | `00000` | `IE = 1` (Kernel only) |
| `DI` | SYS | `111` | `0000` | `0000` | `00001` | `IE = 0` (Kernel only) |
| `JR` | SYS | `111` | `0000` | `Rs` | `00010` | `PC = Rs` |
| `CALLR` | SYS | `111` | `0000` | `Rs` | `00011` | `r14 (lr) = call_inst_PC + 1; PC = Rs` |
| `RETI` | SYS | `111` | `0000` | `0000` | `00100` | `PC = IPC; MODE = PMODE; IE = PIE; SP_MODE = PSP_MODE` (Kernel only) |
| `SYSCALL` | SYS | `111` | `0000` | `imm4` | `00101` | `IPC = PC + 1; PMODE = MODE; PIE = IE; PSP_MODE = SP_MODE; MODE = 0; IE = 0; SP_MODE = 0; PC = RAM[0x0020 + imm4]` |
| `WFI` | SYS | `111` | `0000` | `0000` | `00110` | Wait for interrupt (Kernel only; halts clock until `(IRQ_PEND & IRQ_MASK) != 0`; vectors to ISR if `IE=1`, resumes at `PC+1` if `IE=0`, traps to Vector 2 in User Mode) |

---

## Pseudo-Instructions

The MARC-16 assembler provides intuitive pseudo-instructions that expand into optimal 1- or 2-instruction sequences:

### **LI16 Rd, imm16** — Load full 16-bit constant or label address

```assembly
li16 r1, 0xABCD
# Expands to:
movi r1, 0xCD        # Load low byte (upper byte cleared)
lui  r1, 0xAB        # Load high byte, low byte preserved (r1 = 0xABCD)
```

*(Note: If `imm16 <= 0x00FF`, the assembler emits a single `movi Rd, imm8`; otherwise it emits `movi` + `lui`. `lui` alone preserves the low byte of `Rd`, so it cannot be used by itself to build a constant such as `0xFF00` unless the low byte of `Rd` is already zero.)*

### **RET** — Return from subroutine

```assembly
ret
# Expands to:
jr r14               # Jump to return address stored in Link Register r14 (lr)

```

### **CLR Rd** — Clear register to zero

```assembly
clr r1
# Expands to:
xor r1, r1           # r1 = r1 ^ r1 = 0x0000

```

### **NOP** — No operation

```assembly
nop
# Expands to:
mov r0, r0           # Harmless single-cycle register copy

```

---

## Calling Convention (MARC-16 ABI)

* **Function Arguments**: Passed in **`r1`–`r4**` (`a0`–`a3`). Additional arguments are pushed onto the stack right-to-left.
* **Return Value**: 16-bit result returned in **`r1`** (`a0`); 32-bit result returned in **`r2:r1`** (`a1:a0`).
* **Return Address (`lr`)**: Stored in **`r14` (`lr`)**. Leaf functions execute `ret` (`jr r14`) directly without touching memory. Non-leaf functions save `r14` at function entry (`push r14`) and restore it before returning (`pop r14` followed by `jr r14`).
* **Callee-Saved Registers**: **`r8`–`r13**` (`s0`–`s5`) and **`r15` (`sp`)** must be preserved by any called function.
* **Caller-Saved Registers**: **`r0`–`r7**` and **`r14` (`lr`)** may be freely modified by a callee.

---

## Privilege Modes & Hardware Protection Model

MARC-16 implements a two-level hardware privilege architecture controlled by the internal `MODE` register (`CPU_STATUS[1]` at `0xFF07`):

| Mode | `MODE` Bit | Access Rights & Capabilities |
| :--- | :---: | :--- |
| **Kernel Mode** | `0` | **Full hardware access.** Unrestricted R/W access to all RAM (`0x0000–0xFEFF`) and MMIO (`0xFF00–0xFFFF`). MPU write bounds are bypassed. All `SYS` instructions (`ei`, `di`, `reti`, `wfi`) are permitted. Stack mode (`SP_MODE`) can be dynamically set to `0` (`KSP`) or `1` (`USP`). |
| **User Mode** | `1` | **Restricted sandbox.** Direct MMIO reads/writes (`0xFF00–0xFFFF`) are blocked. Instruction fetch (`PC`) is bounded to `[MPU_BASE .. MPU_LIMIT]` (violation triggers **Vector 3**). RAM writes (`st`, `push`, `xchg`) are restricted to `[MPU_BASE .. MPU_LIMIT]` when `MPU_CTRL[0] == 1`. Privileged `SYS` instructions (`ei`, `di`, `reti`, `wfi`) trap to **Vector 2**. Stack pointer is locked to `USP` (`SP_MODE == 1`). |

### Banked Stack Pointers (`KSP` & `USP`) Controlled via `SP_MODE` & `CPU_USP`

To guarantee complete stack isolation between unprivileged applications and the operating system kernel, MARC-16 implements **Register-Controlled Banked Stack Pointers**:
* **Physical Register Duplication**: The CPU contains two distinct physical 16-bit stack registers:
  * `r15_kernel` (`KSP`): Dedicated kernel stack pointer (initialized to `0xFEFF`).
  * `r15_user` (`USP`): Dedicated user application stack pointer.
* **Stack Mode in System Register (`CPU_STATUS[9]`)**: Mapping of the active physical register to architectural register `r15` is controlled by the **`SP_MODE`** bit:
  * `SP_MODE == 0`: `r15` routes to `KSP` (Kernel Stack).
  * `SP_MODE == 1`: `r15` routes to `USP` (User Stack).
* **Two Clean Access Mechanisms for the Kernel (`MODE == 0`)**:
  1. **Direct MMIO Window (`CPU_USP` at `0xFF0C`)**: The kernel can read or write `r15_user` (`USP`) directly via `ld`/`st` at `0xFF0C` while keeping `SP_MODE == 0` (`KSP` active). This is the fastest way to initialize or swap a task's stack pointer during context switches without changing `SP_MODE`.
  2. **Direct Stack Mode Switching (`SP_MODE = 1` in `CPU_STATUS`)**: When the kernel wants to build or inspect a user stack frame using native `r15` instructions (`push`, `pop`, `mov r15, rX`, `mov rX, r15`), it can set `SP_MODE = 1` in `CPU_STATUS` (`0xFF07`). Writes to `CPU_STATUS` are **hardware-serialized** (triggering a 2-cycle pipeline flush), ensuring that the immediately following instruction in `ID` decodes `r15` using the updated `SP_MODE` without requiring manual `nop` padding.
* **User Mode Protection**: When executing in User Mode (`MODE == 1`), `SP_MODE` is strictly locked to `1` (`USP`), and user code cannot access or modify `CPU_STATUS` or `CPU_USP`.

### Mode Transitions & Software Nested Interrupts

1. **Hardware Reset**:
   * Initializes `MODE <= 0`, `PMODE <= 0`, `IE <= 0`, `PIE <= 0`, `DOUBLE_FAULT <= 0`, `SP_MODE <= 0`, and `PSP_MODE <= 0` (Kernel Mode using `KSP`).
   * Active stack pointer is `KSP` (initialized to `0xFEFF`).

2. **Trap / IRQ / Syscall Entry (User or Kernel → Kernel)**:
   Whenever a hardware IRQ (`IRQ 0..15`), a synchronous CPU exception (Vectors `1..3`: Illegal Instruction, Privilege Fault, MPU Fault), or `syscall 0..15` occurs, hardware atomically executes:

   $$IPC \leftarrow \text{return\textunderscore{}pc} \quad (\text{faulting PC for exceptions; next PC for IRQs; } \text{PC} + 1 \text{ for syscall})$$

   $$PMODE \leftarrow MODE, \quad PIE \leftarrow IE, \quad \text{PSP\textunderscore{}MODE} \leftarrow \text{SP\textunderscore{}MODE}$$

   $$MODE \leftarrow 0 \ (\text{Kernel}), \quad IE \leftarrow 0, \quad \text{SP\textunderscore{}MODE} \leftarrow 0 \ (\text{KSP active})$$

   * **Double Fault / Kernel Panic Detection**: If a synchronous CPU exception (Vectors `1..3`) occurs while the CPU is **already in Kernel Mode** (`MODE == 0`), hardware sets the **`DOUBLE_FAULT`** flag (`CPU_STATUS[8] <= 1`) indicating an unrecoverable kernel panic.

3. **Software Nested Interrupts Pattern**:
   Because `IPC`, `PMODE`, and `PIE` are single-level shadow registers, interrupt handlers that require preemption (nested interrupts) must preserve them on the kernel stack:
   * **ISR Prologue (enabling nesting)**:
     ```assembly
     push r0                  # Save scratch registers on KSP
     push r1
     li16 r0, 0xFF00          # Base address of Slot 0
     ld   r1, [r0 + 6]        # Read CPU_IPC
     push r1                  # Save IPC onto KSP
     ld   r1, [r0 + 7]        # Read CPU_STATUS (saves PMODE, PIE, HW_VEC_ID, SYS_VEC_ID)
     push r1                  # Save CPU_STATUS onto KSP
     st   r_new_mask, [r0 + 4]# Set IRQ_MASK to allow only higher-priority IRQs
     ei                       # Enable interrupts (nested interrupts now active)
     ```
   * **ISR Epilogue**:
     ```assembly
     di                       # Mask interrupts before restoring context
     pop  r1                  # Pop saved CPU_STATUS
     st   r1, [r0 + 7]        # Restore CPU_STATUS (hardware-serialized)
     pop  r1                  # Pop saved IPC
     st   r1, [r0 + 6]        # Restore CPU_IPC
     pop  r1                  # Restore scratch registers
     pop  r0
     reti                     # Atomically restore PC <= IPC, MODE <= PMODE, IE <= PIE, SP_MODE <= PSP_MODE
     ```

4. **Trap Return (`reti` — Kernel → Previous Mode)**:
   Executing `reti` in Kernel Mode atomically restores processor execution state:

   $$PC \leftarrow IPC, \quad MODE \leftarrow PMODE, \quad IE \leftarrow PIE, \quad \text{SP\textunderscore{}MODE} \leftarrow \text{PSP\textunderscore{}MODE}$$

   * To launch or switch to a User task, the RTOS scheduler writes the task's user stack pointer to **`CPU_USP` (`0xFF0C`)** (or switches `SP_MODE = 1` and writes `r15`), writes the entry address to **`CPU_IPC` (`0xFF06`)**, sets `PMODE = 1`, `PSP_MODE = 1`, and `PIE = 1` in **`CPU_STATUS` (`0xFF07`)**, and executes `reti`.
   * Attempting to execute `reti` while in User Mode (`MODE == 1`) is intercepted by the decoder and triggers **Vector 2 (`Privilege Fault`)**.

---

## Memory-Mapped I/O (MMIO) Architecture & Register Reference

### How MMIO Works in MARC-16

MARC-16 maps all internal system controllers and external hardware peripherals into the upper 256 words of the address space (**`0xFF00–0xFFFF`**).

1. **Hardware Address Decoding**: Whenever the CPU executes a memory instruction (`ld`, `st`, `xchg`), the bus combinational decoder checks `mem_addr[15:8] == 8'hFF`.
2. **Zero-Wait-State Access**: If `mem_addr[15:8] == 8'hFF`, BRAM write enable is suppressed (`bram_we = 0`) and the request is routed directly to the MMIO register bank according to `mem_addr[7:0]`.
3. **Compact Offset Addressing**: Because each peripheral block is aligned to an 8- or 16-word boundary, device drivers can load the peripheral base address once (e.g., `li16 r1, 0xFF00`) and access all sub-registers in a single instruction using **`ld Rd, [r1 + offset]`** and **`st Rd, [r1 + offset]`**.

### MMIO Slot Allocation (`0xFF00–0xFFFF`)

Slot 3 is officially reserved (free/unallocated) alongside slots 8..15:

```text
0xFF00..0xFF0F (Slot 0): Timer (00-03), IRQ/Status (04-07), MPU (08-0B), CPU_USP (0C)
0xFF10..0xFF1F (Slot 1): UART (10-13)
0xFF20..0xFF2F (Slot 2): GPIO (20-23)
0xFF30..0xFF3F (Slot 3): [RESERVED / FREE]
0xFF40..0xFF4F (Slot 4): SPI Master (40-44)
0xFF50..0xFF5F (Slot 5): I2C Master (50-53)
0xFF60..0xFF6F (Slot 6): DMA Controller (60-64)
0xFF70..0xFF7F (Slot 7): PWM Generator (70-74)
0xFF80..0xFFFF (Slots 8..15): [RESERVED FOR CUSTOM PERIPHERALS]
```

### Complete MMIO Register Map (`0xFF00–0xFFFF`)

| Address | Register Name | Access | Reset | Peripheral Block & Summary |
| --- | --- | --- | --- | --- |
| **System Timer (`0xFF00–0xFF03`)** |  |  |  |  |
| `0xFF00` | `TIMER_VAL` | R/W | `0x0000` | Current 16-bit counter value (writing any value clears counter & IRQ flag) |
| `0xFF01` | `TIMER_RELOAD` | R/W | `0xFFFF` | Auto-reload period threshold (defines RTOS SysTick time slice quantum) |
| `0xFF02` | `TIMER_CTRL` | R/W | `0x0000` | Bit 0: `EN`, Bit 1: `IRQ_EN`, Bits `[3:2]`: `PRESCALER` (`/1`, `/16`, `/64`, `/256`) |
| `0xFF03` | `TIMER_STAT` | R/W1C | `0x0000` | Bit 0: Timer overflow interrupt pending flag (write `1` to clear) |
| **Interrupt Controller & CPU State (`0xFF04–0xFF07`, `0xFF0C`)** |  |  |  |  |
| `0xFF04` | `IRQ_MASK` | R/W | `0x0000` | 16-bit interrupt enable mask (`1` = IRQ line enabled, `0` = masked) |
| `0xFF05` | `IRQ_PEND` | R/W1C | `0x0000` | 16-bit pending IRQ bitmap (read active IRQs; write `1` to acknowledge/clear) |
| `0xFF06` | `CPU_IPC` | R/W | `0x0000` | Direct access to shadow `IPC` register (essential for RTOS context switching) |
| `0xFF07` | `CPU_STATUS` | R/W | `0x0000` | Bits: `[0]`=`IE`, `[1]`=`MODE`, `[2]`=`PMODE`, `[3]`=`PIE`, `[7:4]`=`HW_VEC_ID`, `[8]`=`DOUBLE_FAULT`, `[9]`=`SP_MODE`, `[10]`=`PSP_MODE`, `[14:11]`=`SYS_VEC_ID` |
| `0xFF0C` | `CPU_USP` | R/W | `0x0000` | Kernel mirror window to User Stack Pointer (`USP` / `r15_user`); Kernel Mode access only |
| **Memory Protection Unit — MPU (`0xFF08–0xFF0B`)** |  |  |  |  |
| `0xFF08` | `MPU_BASE` | R/W | `0x0000` | Lower allowed RAM write address boundary for active user task (RTOS must keep `>= 0x0030`) |
| `0xFF09` | `MPU_LIMIT` | R/W | `0xFEFF` | Upper allowed RAM write address boundary for active user task |
| `0xFF0A` | `MPU_CTRL` | R/W | `0x0000` | Bit 0: `MPU_EN` (`1` = enforce bounds on `st`/`push`/`xchg` while `MODE == 1`) |
| `0xFF0B` | `MPU_FAULT_ADDR` | R | `0x0000` | Latches the offending `mem_addr` that triggered Vector 3 (`MPU / MMIO Fault`) |
| **UART Serial Controller (`0xFF10–0xFF13`)** |  |  |  |  |
| `0xFF10` | `UART_DATA` | R/W | `0x0000` | Write `[7:0]`: transmit byte via TX; Read `[7:0]`: pop received byte from RX |
| `0xFF11` | `UART_STATUS` | R/W1C | `0x0000` | `[0]`=`TX_BUSY`, `[1]`=`RX_READY`, `[2]`=`RX_OVERRUN` |
| `0xFF12` | `UART_BAUD` | R/W | `0x01B2` | Baud rate clock divider (`CLK_HZ / BAUD`, default `434` for 115200 at 50 MHz) |
| `0xFF13` | `UART_CTRL` | R/W | `0x0000` | `[0]`=`RX_IRQ_EN` (IRQ 2), `[1]`=`TX_IRQ_EN` (IRQ 1) |
| **GPIO & Board I/O (`0xFF20–0xFF23`)** |  |  |  |  |
| `0xFF20` | `GPIO_OUT` | R/W | `0x0000` | Output pin latch register (Bits `[5:0]` drive Tang Nano 20K onboard LEDs) |
| `0xFF21` | `GPIO_IN` | R | — | Live synchronized input pin states (Bits `[1:0]` read Tang Nano 20K buttons) |
| `0xFF22` | `GPIO_DIR` | R/W | `0x003F` | Pin direction (`1` = Output, `0` = Input) |
| `0xFF23` | `GPIO_IRQ_EN` | R/W | `0x0000` | Rising-edge interrupt enable mask for input pins (triggers IRQ 3) |
| **Reserved Slot 3 (`0xFF30–0xFF3F`)** |  |  |  |  |
| `0xFF30–0xFF3F` | — | — | — | Reserved / Free slot |
| **SPI Master Controller (`0xFF40–0xFF4F`, Slot 4)** |  |  |  |  |
| `0xFF40` | `SPI_DATA` | R/W | `0x0000` | Write: transmit a byte/word on MOSI; Read: fetch the received word from MISO |
| `0xFF41` | `SPI_STATUS` | R | `0x0002` | `[0]`=`BUSY` (1 = transfer in progress), `[1]`=`TX_READY`, `[2]`=`RX_READY` |
| `0xFF42` | `SPI_CTRL` | R/W | `0x0000` | `[0]`=`EN`, `[1]`=`IRQ_EN` (IRQ 4), `[2]`=`CPOL`, `[3]`=`CPHA`, `[4]`=`WORD_16B` (0 = 8-bit, 1 = 16-bit) |
| `0xFF43` | `SPI_CLK_DIV` | R/W | `0x0004` | SCK divider: `F_SCK = F_CLK / (2 × (DIV + 1))` |
| `0xFF44` | `SPI_CS` | R/W | `0x000F` | Chip Select pin control (active low; `[3:0]` selects one of 4 devices) |
| **I2C Master Controller (`0xFF50–0xFF5F`, Slot 5)** |  |  |  |  |
| `0xFF50` | `I2C_DATA` | R/W | `0x0000` | Byte to transmit, or byte received from the SDA line |
| `0xFF51` | `I2C_STATUS` | R | `0x0000` | `[0]`=`TIP` (Transfer in Progress), `[1]`=`RX_ACK` (0 = ACK received, 1 = NACK), `[2]`=`BUS_BUSY` |
| `0xFF52` | `I2C_CTRL` | R/W | `0x0000` | `[0]`=`START`, `[1]`=`STOP`, `[2]`=`READ`, `[3]`=`WRITE`, `[4]`=`ACK_VALUE`, `[5]`=`IRQ_EN` (IRQ 5) |
| `0xFF53` | `I2C_PRESCALE` | R/W | `0x007C` | SCL clock divider: `F_SCL = F_CLK / (4 × (PRESCALE + 1))` (`0x007C` = 124 → 100 kHz at 50 MHz; `0x001E` ≈ 400 kHz) |
| **DMA Controller (`0xFF60–0xFF6F`, Slot 6)** |  |  |  |  |
| `0xFF60` | `DMA_SRC` | R/W | `0x0000` | 16-bit source address (RAM or MMIO; directly increments if `SRC_INC=1`, live progress readable) |
| `0xFF61` | `DMA_DST` | R/W | `0x0000` | 16-bit destination address (RAM or MMIO; directly increments if `DST_INC=1`, live progress readable) |
| `0xFF62` | `DMA_COUNT` | R/W | `0x0000` | Number of 16-bit words to transfer (`0` = idle or finished; decrements during transfer) |
| `0xFF63` | `DMA_CTRL` | R/W | `0x0000` | Configuration and start register (Bit 1: `IRQ_EN` for IRQ 6) |
| `0xFF64` | `DMA_STATUS` | R/W1C | `0x0000` | Status and error diagnostics register |
| **PWM Controller (`0xFF70–0xFF7F`, Slot 7)** |  |  |  |  |
| `0xFF70` | `PWM_PERIOD` | R/W | `0x00FF` | Timer counter period (sets the base PWM frequency) |
| `0xFF71` | `PWM_CH0_DUTY` | R/W | `0x0000` | Channel 0 compare threshold (duty cycle from 0 to `PWM_PERIOD`) |
| `0xFF72` | `PWM_CH1_DUTY` | R/W | `0x0000` | Channel 1 compare threshold |
| `0xFF73` | `PWM_CH2_DUTY` | R/W | `0x0000` | Channel 2 compare threshold |
| `0xFF74` | `PWM_CTRL` | R/W | `0x0000` | `[0]`=`EN`, `[3:1]`=`CH0..CH2_EN`, `[5:4]`=`PRESCALER` (`/1`, `/8`, `/64`, `/256`) |
| **Custom Peripheral Slots (`0xFF80–0xFFFF`, Slots 8..15)** |  |  |  |  |
| `0xFF80–0xFFFF` | — | — | — | Reserved for custom user FPGA peripherals |

---

### Detailed Peripheral Block Descriptions

#### 1. System Timer (`0xFF00–0xFF03`)

Provides deterministic periodic interrupts (IRQ 0 / `0x0010`) for the RTOS scheduler:

* **`TIMER_VAL` (`0xFF00`)**: Increments by 1 on every prescaled clock tick when enabled. Writing any value resets `TIMER_VAL` to `0x0000` and clears the pending interrupt flag.
* **`TIMER_RELOAD` (`0xFF01`)**: When `TIMER_VAL == TIMER_RELOAD`, the counter automatically resets to `0x0000` on the next tick and asserts the Timer IRQ flag (IRQ 0).
* **`TIMER_CTRL` (`0xFF02`)**:
* **Bit `0` (`EN`)**: `1` = Timer counting enabled, `0` = Timer paused.
* **Bit `1` (`IRQ_EN`)**: `1` = Assert IRQ line 0 upon reload match.
* **Bits `[3:2]` (`PRESCALER`)**: Clock divider selector using a synchronous clock-enable pulse (`tick_en`):
* `00`: $\div 1$ (20 ns tick at 50 MHz; max period = 1.31 ms)
* `01`: $\div 16$ (320 ns tick at 50 MHz; max period = 20.97 ms)
* `10`: $\div 64$ (1.28 µs tick at 50 MHz; max period = 83.88 ms)
* `11`: $\div 256$ (5.12 µs tick at 50 MHz; max period = 335.54 ms)





#### 2. Interrupt Controller, CPU State & Stack Window (`0xFF04–0xFF07`, `0xFF0C`)

Manages asynchronous hardware interrupt lines (`IRQ 0..15`), exposes shadow `IPC` for preemptive multitasking, and provides access to processor status and the user stack:

* **`IRQ_MASK` (`0xFF04`) & `IRQ_PEND` (`0xFF05`)**: Each bit $i \in [0..15]$ corresponds to `IRQ i`. When a peripheral asserts an interrupt, bit $i$ latches to `1` in `IRQ_PEND`. If `IE == 1` and `(IRQ_PEND & IRQ_MASK) != 0`, the priority encoder selects the lowest-numbered active bit (highest priority) and vectors the CPU to `RAM[0x0010 + irq_id]`.
* **`CPU_IPC` (`0xFF06`)**: Because MARC-16 saves the interrupted program counter in the internal `IPC` register rather than pushing it automatically, the RTOS SysTick handler performs a context switch by reading `CPU_IPC` via `ld r1, [rBase + 6]`, preserving `r1` and `r0–r14` in the outgoing task's context, saving/restoring the user stack pointer via `CPU_USP` (`[rBase + 12]`) (or switching stack mode via `CPU_STATUS[9] (SP_MODE)`), loading the incoming task's resume PC into `CPU_IPC`, and executing `reti`.
* **`CPU_STATUS` (`0xFF07`)**: Processor control and status register. Writes (`st`, `xchg`) to `CPU_STATUS` are **hardware-serialized** (triggering a pipeline flush and restarting instruction fetch at `PC + 1`), guaranteeing that changes to `SP_MODE`, `MODE`, or `IE` take effect before the next instruction is fetched and decoded:

  | Bits | Name | Access | Reset | Description |
  |:---:|:---:|:---:|:---:|:---|
  | `0` | `IE` | R | `0` | Current global interrupt status (`1` = enabled, `0` = masked) |
  | `1` | `MODE` | R/W (Kernel) | `0` | Current privilege level (`0` = Kernel Mode, `1` = User Mode) |
  | `2` | `PMODE` | R/W (Kernel) | `0` | Previous privilege level before interrupt/trap/syscall |
  | `3` | **`PIE`** | R/W (Kernel) | `0` | **Previous Interrupt Enable**: state of `IE` prior to entering last handler/trap |
  | `[7:4]` | **`HW_VEC_ID`** | R | `0x0` | **Hardware Interrupt Vector ID**: identifier of active peripheral interrupt line (`IRQ 0..15`) |
  | `8` | **`DOUBLE_FAULT`** | R/W1C (Kernel) | `0` | **Kernel Panic Flag**: latched to `1` if an exception/fault occurs in Kernel Mode (`MODE == 0`) |
  | `9` | **`SP_MODE`** | R/W (Kernel) | `0` | **Stack Pointer Mode**: `0` = `KSP` (`r15_kernel`) active as `r15`, `1` = `USP` (`r15_user`) active as `r15` |
  | `10` | **`PSP_MODE`** | R/W (Kernel) | `0` | **Previous Stack Pointer Mode**: latched from `SP_MODE` on trap/IRQ entry, restored by `reti` |
  | `[14:11]` | **`SYS_VEC_ID`** | R | `0x0` | **System Vector ID**: identifier of active software syscall (`0..15`) or CPU exception (`1..3`) |
  | `15` | *-* | R | `0` | Reserved (read as `0`) |

  **State Transition Logic:**
  * **Entry to Hardware Peripheral IRQ:**
    $$IPC \leftarrow \text{next\textunderscore{}pc}$$
    $$PMODE \leftarrow MODE, \quad PIE \leftarrow IE, \quad \text{PSP\textunderscore{}MODE} \leftarrow \text{SP\textunderscore{}MODE}$$
    $$MODE \leftarrow 0 \ (\text{Kernel}), \quad IE \leftarrow 0, \quad \text{SP\textunderscore{}MODE} \leftarrow 0 \ (\text{KSP active})$$
    $$\text{HW\textunderscore{}VEC\textunderscore{}ID} \leftarrow \text{irq\textunderscore{}id}$$
  * **Entry to Software Syscall / CPU Exception:**
    $$IPC \leftarrow \text{return\textunderscore{}pc} \quad (\text{faulting PC for exceptions; } \text{PC} + 1 \text{ for syscall})$$
    $$PMODE \leftarrow MODE, \quad PIE \leftarrow IE, \quad \text{PSP\textunderscore{}MODE} \leftarrow \text{SP\textunderscore{}MODE}$$
    $$MODE \leftarrow 0 \ (\text{Kernel}), \quad IE \leftarrow 0, \quad \text{SP\textunderscore{}MODE} \leftarrow 0 \ (\text{KSP active})$$
    $$\text{SYS\textunderscore{}VEC\textunderscore{}ID} \leftarrow imm4 \text{ or } \text{exc\textunderscore{}id}$$
  * **Exit via `reti` (Kernel Mode only):**
    $$PC \leftarrow IPC, \quad MODE \leftarrow PMODE, \quad IE \leftarrow PIE, \quad \text{SP\textunderscore{}MODE} \leftarrow \text{PSP\textunderscore{}MODE}$$

* **`CPU_USP` (`0xFF0C`)**: User Stack Pointer MMIO mirror window (Kernel Mode only). Allows the RTOS kernel to read or write `USP` (`r15_user`) directly via `ld`/`st` while keeping `SP_MODE == 0` (`KSP`), avoiding any need to toggle `SP_MODE` when initializing or switching tasks.

#### 3. Memory Protection Unit — MPU (`0xFF08–0xFF0B`)

Isolates unprivileged User tasks (`MODE == 1`) in an RTOS so a buggy task or stack overflow cannot corrupt the kernel, vector tables, peripheral registers, or other tasks:

* **Active Condition**: Hardware protection is enforced whenever the CPU is in **User Mode (`MODE == 1`)**. In Kernel Mode (`MODE == 0`) the CPU has unrestricted access to all memory and MMIO, without needing to clear `MPU_CTRL[0]`.
* **Instruction Fetch Protection (IF Stage)**: In User Mode (`MODE == 1`), the fetched instruction address (`PC`) is bounded by `[MPU_BASE .. MPU_LIMIT]`: violation = $(PC < \text{MPU\textunderscore{}BASE}) \lor (PC > \text{MPU\textunderscore{}LIMIT})$. Any attempt to execute instructions outside this range (e.g. jumping to kernel vectors or unmapped RAM) suppresses fetch and traps to **Vector 3 (`MPU / MMIO Fault`)** before execution.
* **MMIO Protection**: Any read or write (`ld`, `st`, `push`, `pop`, `xchg`) targeting `0xFF00–0xFFFF` while `MODE == 1` is unconditionally blocked and triggers **Vector 3 (`0x0003`)**.
* **RAM Write Bounds**: When `MODE == 1` and `MPU_CTRL[0] (MPU_EN) == 1`, hardware combinational comparators check every memory write (`st`, `push`, `xchg`) against `[MPU_BASE .. MPU_LIMIT]`: violation = (mem_addr < MPU_BASE) ∨ (mem_addr > MPU_LIMIT)
  *(Requirement: the RTOS kernel must configure `MPU_BASE >= 0x0030` so User tasks cannot overwrite the Exception (`0x0000–0x000F`), Hardware IRQ (`0x0010–0x001F`) or Syscall (`0x0020–0x002F`) vector tables.)*
* **DMA parity**: DMA transfers marked `DMA_CTRL[6] (USER_MODE) = 1` follow the same rules (MMIO blocked, RAM writes bounded) with the kernel-latched bounds; see the DMA section. DMA violations are reported through `DMA_STATUS` and IRQ 6, not Vector 3.
* **Fault Trap Behavior**: If a violation occurs, the write/read signal to BRAM/MMIO is suppressed in the same clock cycle, the offending address is latched into `MPU_FAULT_ADDR` (`0xFF0B`), and the CPU traps to **Vector 3 (`0x0003`)** using the standard trap entry (`IPC <= PC`, `PMODE <= 1`, `PIE <= IE`, `PSP_MODE <= SP_MODE`, `MODE <= 0`, `IE <= 0`, `SP_MODE <= 0`). Because entering Kernel Mode automatically bypasses MPU enforcement, `MPU_CTRL[0]` is **not** modified by the fault.

#### 4. UART Serial Interface (`0xFF10–0xFF13`)

Provides full-duplex 8N1 serial communication connected to the Tang Nano 20K onboard USB-UART bridge:

* **`UART_STATUS` (`0xFF11`)**:
* **Bit `0` (`TX_BUSY`)**: `1` while the transmit shift register is actively shifting out a frame; `0` when ready for a new byte.
* **Bit `1` (`RX_READY`)**: `1` when a complete byte has been received in `UART_DATA` (automatically cleared upon reading `0xFF10`).
* **Bit `2` (`RX_OVERRUN`)**: `1` if a new byte arrived before the previous byte was read.

#### 5. SPI Master Controller (`0xFF40–0xFF4F`, Slot 4)

Designed for high-speed communication with SD cards, W25Q flash memory, and SPI displays (ST7789, ILI9341). Each peripheral slot is aligned to 16 words, so all registers are reachable with `ld`/`st` using the 4-bit offset `[Rs + imm4]`.

* **`SPI_STATUS` (`0xFF41`)**: reset value `0x0002` (`TX_READY = 1`, controller idle).
* **`SPI_CLK_DIV` (`0xFF43`)**: `F_SCK = F_CLK / (2 × (DIV + 1))`; the reset value `4` gives 5 MHz at a 50 MHz system clock.
* **`SPI_CS` (`0xFF44`)**: Chip Select lines are active low; the reset value `0xF` leaves all four devices deselected.

#### 6. I2C Master Controller (`0xFF50–0xFF5F`, Slot 5)

Designed for slow sensors, real-time clocks (RTC), and SSD1306 OLED displays. A hardware finite-state machine generates the START and STOP sequences and handles the ACK bit.

* **`I2C_PRESCALE` (`0xFF53`)**: The FSM splits every `SCL` period into **4 phases** (quarter-periods: set `SDA` while `SCL = 0`, raise `SCL`, sample while `SCL = 1`, lower `SCL`), each lasting `PRESCALE + 1` system clocks:
  $$F_{\text{SCL}} = \frac{F_{\text{CLK}}}{4 \times (\text{PRESCALE} + 1)}$$
  * Standard Mode (100 kHz at 50 MHz): `PRESCALE = 124` (`0x007C`, the reset value), since `50 000 000 / (4 × 125) = 100 000`.
  * Fast Mode (400 kHz at 50 MHz): `PRESCALE = 30` (`0x001E`), giving ≈ 403 kHz (`50 000 000 / (4 × 31)`).

#### 7. Direct Memory Access Controller — DMA (`0xFF60–0xFF6F`, Slot 6)

The DMA controller operates as a second active Master on the internal Wishbone bus alongside the CPU core (see *System Interconnect & Wishbone B4 Bus Specification* below). It performs hardware transfers of 16-bit words between RAM blocks (`0x0000–0xFEFF`) and MMIO peripheral registers (`0xFF00–0xFFFF`) without involving the CPU pipeline.

With the removal of `REPEAT` mode, shadow registers for base addresses are eliminated. During transfer, the `DMA_SRC` and `DMA_DST` registers directly increment (if `SRC_INC`/`DST_INC` is enabled), allowing software to poll or read the current copy progress from them at any moment.

##### `DMA_CTRL` format (`0xFF63`)

```text
 15  ...  7      6         5        4         3          2         1        0
┌───────────┬───────────┬─────────┬───────┬──────────┬──────────┬────────┬───────┐
│ Reserved  │ USER_MODE │ PRIO_EN │   0   │ DST_INC  │ SRC_INC  │ IRQ_EN │ START │
└───────────┴───────────┴─────────┴───────┴──────────┴──────────┴────────┴───────┘
```

* **Bit `0` (`START`)**: Writing `1` begins the block transfer. Automatically cleared to `0` by hardware after transferring the last word.
* **Bit `1` (`IRQ_EN`)**: Hardware interrupt enable on **IRQ 6 (`0x0016`)** after exhausting the word counter (`DMA_COUNT`) or upon error (`ERR_MPU` / `ERR_ADDR`).
* **Bit `2` (`SRC_INC`)**: Source address auto-increment: `1` = `DMA_SRC` increases by `+1` after every word read (buffer read mode); `0` = address is static (reading from a peripheral FIFO register such as `UART_DATA` or `SPI_DATA`).
* **Bit `3` (`DST_INC`)**: Destination address auto-increment: `1` = `DMA_DST` increases by `+1` after every word written (buffer write mode); `0` = address is static (writing into a peripheral FIFO register).
* **Bit `4`**: **Reserved (0)** (circular `REPEAT` mode has been removed).
* **Bit `5` (`PRIO_EN`)**: **Bus arbitration priority mode**:
  * `0` = Cycle Stealing (CPU priority, default).
  * `1` = Burst Mode (DMA priority / bus capture).
* **Bit `6` (`USER_MODE`)**: **Protection domain of the transfer**, written only by the kernel (the DMA registers are inside the MMIO barrier):
  * `0` = **Kernel transfer**: unrestricted transfer (no MPU limits).
  * `1` = **User-domain transfer** (performed on behalf of a User task): hardware validates address ranges at transfer start.
* **Bits `[15:7]`**: Reserved (read as `0`).

> **Validation Rule:** If `DMA_COUNT == 0` at the moment `START = 1` is written, the controller does not perform any address math or bus requests, immediately setting `DONE = 1`.

##### `DMA_STATUS` format (`0xFF64`)

* **Bit `0` (`BUSY`)** [R]: `1` — a transfer is actively running on the bus; `0` — the channel is idle.
* **Bit `1` (`DONE`)** [R/W1C]: `1` — the transfer of `DMA_COUNT` words completed successfully. Cleared by writing `1`.
* **Bit `2` (`ERR_MPU`)** [R/W1C]: `1` — a User-domain transfer (`USER_MODE = 1`) was **rejected at `START`** because its source or destination range touches MMIO (`0xFF00–0xFFFF`), or its destination range leaves `[MPU_BASE .. MPU_LIMIT]`. No word has been transferred and `BUSY` was never set.
* **Bit `3` (`ERR_ADDR`)** [R/W1C]: `1` — Wishbone bus error (`wb_err_i`) caused by access to a nonexistent address, such as an unmapped MMIO slot. (MARC-16 uses 16-bit word addressing, so there is no unaligned-access condition.)

##### Bus arbitration modes

The core bus arbiter controls access to Port B of the dual-port BSRAM and to the peripheral window according to `DMA_CTRL[5]`:

```text
                     ┌──────────────────┐
                     │   DMA_CTRL[5]    │
                     └────────┬─────────┘
            PRIO_EN = 0       │       PRIO_EN = 1
       ┌──────────────────────┴──────────────────────┐
       ▼                                             ▼
[Cycle Stealing Mode]                        [Burst Mode]
- CPU has priority.                          - DMA has priority.
- DMA steps only during ALU/JMP cycles.      - CPU stalls on any RAM access.
- Zero added latency for user code.          - Maximum throughput.
- Default mode for the RTOS.

```

**Mode 0 — Cycle Stealing (CPU priority, `PRIO_EN = 0`)**

* **Mechanism:** The CPU has the highest priority for data memory access. The DMA takes the bus only in cycles when the CPU is busy computing (ALU, shifts, `jmp`/`jz` jumps) and is not asserting the `cpu_mem_req` strobe.
* **Conflict behavior:** If, during a block transfer, the CPU executes a memory-access instruction (`ld`, `st`, `push`, `pop`, `xchg`), the arbiter grants the bus to the CPU in that same cycle and freezes the internal DMA counters. The transfer resumes immediately after the CPU cycle completes.
* **Purpose:** Background memory copying in an RTOS without degrading response time to system events and without delaying interrupt handlers.

**Mode 1 — Burst Transfer (DMA priority, `PRIO_EN = 1`)**

* **Mechanism:** The DMA takes exclusive control of the data bus until the number of words specified in `DMA_COUNT` has been transferred.
* **Conflict behavior:** If the CPU tries to access Port B (data memory or MMIO) in Burst mode, the bus arbiter asserts **`cpu_stall`**, temporarily halting the CPU pipeline in the MEM phase until the DMA releases the bus or finishes the current burst.
* **Purpose:** Time-critical data streams (for example, pushing a pixel frame to an SPI display, reading SD card sectors at high speed, jitter-free audio streaming).

##### Hardware protection and MPU interaction

1. **Configuration privileges:** The DMA registers (`0xFF60–0xFF64`) are covered by the general MMIO barrier. Any direct access to them from a User task (`MODE == 1`) is blocked and raises **Vector 3 (`MPU / MMIO Fault`)**. DMA setup, including the `USER_MODE` bit, is performed exclusively by the kernel (`MODE == 0`) through `syscall`. A task can never set `USER_MODE = 0` for itself.
2. **Rights parity with the CPU:** A User-domain transfer (`USER_MODE = 1`) has exactly the rights of the CPU in User Mode:

   | Access | CPU in User Mode | DMA with `USER_MODE = 1` |
   | :--- | :--- | :--- |
   | MMIO read/write (`0xFF00–0xFFFF`) | Blocked | Blocked (source **and** destination) |
   | RAM read | Allowed | Allowed |
   | RAM write | Only inside `[MPU_BASE .. MPU_LIMIT]` | Only inside the latched `[MPU_BASE .. MPU_LIMIT]` |

   For a User-domain transfer the bounds check on the destination is always enforced, even if `MPU_CTRL[0] == 0`; a transfer marked as User-domain can therefore never become unrestricted by accident. As for the CPU, the kernel must keep `MPU_BASE >= 0x0030` so the vector tables stay protected.
3. **Atomic validation at `START` (all-or-nothing):** When `START` is written with `USER_MODE = 1`, the DMA validates the **whole** transfer range before issuing the first bus cycle, and latches `MPU_BASE` and `MPU_LIMIT` into internal shadow registers (`dma_mpu_base`, `dma_mpu_limit`) in that same cycle. With `COUNT = DMA_COUNT` and the increment flags `SRC_INC`/`DST_INC`:
   * `src_last = SRC_INC ? SRC + COUNT - 1 : SRC` and `dst_last = DST_INC ? DST + COUNT - 1 : DST`, computed in 17 bits so address wrap-around (carry out of bit 15) counts as a violation.
   * violation_src = `src_last >= 0xFF00` ∨ carry
   * violation_dst = `dst_last >= 0xFF00` ∨ `DST < dma_mpu_base` ∨ `dst_last > dma_mpu_limit` ∨ carry

   If either condition holds, the transfer **does not start**: `BUSY` stays `0`, `DMA_STATUS[2]` (`ERR_MPU`) is set, no word is read or written, and `DMA_SRC`/`DMA_DST`/`DMA_COUNT` keep their programmed values. Otherwise the transfer is guaranteed to pass every protection check for its entire duration, so no protection error can occur halfway through a copy and leave a partially written buffer.
4. **Context-switch independence:** The checks use only the values latched at `START`. Later changes of `MPU_BASE`/`MPU_LIMIT`/`MPU_CTRL` and the identity of the currently running task have no effect on a transfer in flight. Together with item 3, the outcome of a transfer is a function of its programmed parameters alone and does not depend on the timing of `SysTick` or on CPU bus activity.
5. **Error reporting is asynchronous and DMA-local:** DMA errors (`ERR_MPU`, `ERR_ADDR`) are reported only through `DMA_STATUS` and, when `DMA_CTRL[1] (IRQ_EN) == 1`, through **IRQ 6**. They never raise **Vector 3** and never write `MPU_FAULT_ADDR`, because the CPU may be running an unrelated task when the DMA fails; Vector 3 and `MPU_FAULT_ADDR` are reserved for faults of the CPU's own accesses. The kernel's IRQ 6 handler reads `DMA_STATUS` to see which transfer failed.
6. **`START` with `DMA_COUNT == 0`:** If `DMA_COUNT == 0` at the moment `START = 1` is written, the controller does not perform any mathematical address range checks or bus accesses, immediately setting `DONE = 1`.
7. **Kernel transfers:** With `USER_MODE = 0` none of the checks above apply, and the kernel does not need to touch `MPU_CTRL[0]`. Runtime bus errors (`wb_err_i`, for example an unmapped MMIO slot) can still occur in either domain and set `DMA_STATUS[3]` (`ERR_ADDR`).

##### Example: copying a block of data (MARC-16 assembly)

Copy 256 words from the input buffer at `0x0400` to the output buffer at `0x0800` in Cycle Stealing mode with an interrupt on completion:

```assembly
# Configure the DMA through the MMIO base register
li16 r1, 0xFF60        # r1 = DMA base address

li16 r2, 0x0400        # Source buffer base address
st   r2, [r1 + 0]      # DMA_SRC = 0x0400

li16 r2, 0x0800        # Destination base address
st   r2, [r1 + 1]      # DMA_DST = 0x0800

li16 r2, 256           # Number of 16-bit words
st   r2, [r1 + 2]      # DMA_COUNT = 256

# DMA_CTRL configuration:
# Bit 0 (START)   = 1
# Bit 1 (IRQ_EN)  = 1
# Bit 2 (SRC_INC) = 1 (increment source)
# Bit 3 (DST_INC) = 1 (increment destination)
# Bit 5 (PRIO_EN) = 0 (Cycle Stealing / CPU priority)
# Bit 6 (USER_MODE) = 0 (kernel-owned transfer, no protection checks)
# Value: 0b0000_1111 = 0x000F
movi r2, 0x0F
st   r2, [r1 + 3]      # Start the transfer (DMA_CTRL)

# The CPU continues executing code without pipeline blocking
```

#### 8. PWM Controller (`0xFF70–0xFF7F`, Slot 7)

Three-channel pulse-width modulator with a shared period counter. `PWM_PERIOD` sets the base frequency, and each `PWM_CHn_DUTY` register is a compare threshold in the range `0..PWM_PERIOD`. `PWM_CTRL[0]` is the global enable, `PWM_CTRL[3:1]` enable channels 0–2 individually, and `PWM_CTRL[5:4]` select the prescaler (`/1`, `/8`, `/64`, `/256`).

---

## Processor Pipeline Architecture (5-Stage: IF – ID – EX – MEM – WB)

MARC-16 executes instructions through a classic **5-stage synchronous RISC pipeline** designed for maximum throughput, clean hazard control, and optimal FPGA resource mapping:

```text
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   IF Stage   │────►│   ID Stage   │────►│   EX Stage   │────►│  MEM Stage   │────►│   WB Stage   │
│ Instruction  │     │ Instruction  │     │ Execution /  │     │ Data Memory  │     │ Register     │
│ Fetch        │     │ Decode / Reg │     │ ALU / DSP    │     │ / MMIO Access│     │ Write-Back   │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
   BSRAM Port A         Banked KSP/USP      ALU & 16x16 MULT      BSRAM Port B /      r0-r15 GPRs
  PC Generation        Hazard Detection     Branch Evaluation     Wishbone Bus
```

### 1. Pipeline Stages

1. **IF (Instruction Fetch)**:
   * **Operation**: Fetches 16-bit instruction words from memory using the Program Counter (`PC`).
   * **Hardware Mapping**: Communicates through **Port A** of the internal Dual-Port BSRAM with single-cycle synchronous read latency.
   * **Flow**: Generates `PC + 1` for normal execution or latches target addresses from branch/jump or trap/vector redirection logic.
   * **MPU User Mode Instruction Fetch Check**: In User Mode (`MODE == 1`), hardware validates `PC` against active `[MPU_BASE .. MPU_LIMIT]` bounds. If `PC < MPU_BASE` or `PC > MPU_LIMIT`, the fetch is aborted, a pipeline bubble is injected, `MPU_FAULT_ADDR <= PC`, and the core traps to **Vector 3 (`MPU / MMIO Fault`)**.

2. **ID (Instruction Decode & Register Fetch)**:
   * **Operation**: Decodes instruction fields: opcode `[2:0]`, destination `Rd` / operand `A` `[15:12]`, source `Rs` / operand `B` `[11:8]`, and function code `op5` / offset `imm4` `[7:3]`.
   * **Register Fetch**: Reads operand values from the dual-read-port register file (`r0`–`r15`).
   * **Banked Stack Switching**: Hardware routes access to `r15` or stack operations (`push`/`pop`) to either `r15_kernel` (`KSP`) when `SP_MODE == 0` or `r15_user` (`USP`) when `SP_MODE == 1`. The selected physical bank tag (`sp_bank = SP_MODE`) is latched into `ID/EX` and propagated through `EX/MEM` and `MEM/WB` so that `WB` always writes back to the same physical stack register that was decoded in `ID`.
   * **Hazard Detection**: Evaluates RAW (Read-After-Write) hazards for memory load results and controls pipeline stall logic.

3. **EX (Execute & Address Calculation)**:
   * **Operation**: Computes arithmetic, bitwise logic, barrel shifts, rotations, unary functions (`inc`, `dec`, `not`, `neg`, `clz`), and effective memory addresses (`Rs + imm4` or stack adjustments for `push`/`pop`).
   * **DSP Multiplication**: Single-cycle 16×16 signed/unsigned multiplier mapped onto Gowin FPGA `MULT18X18` DSP primitives (`mul`, `mulh`, `mlhu`).
   * **Branch Evaluation**: Evaluates condition flags for conditional jumps (`jz`, `jnz`) and computes branch target addresses (`PC + sign_extend(imm8)`).

4. **MEM (Memory Access & Protection Enforcement)**:
   * **Operation**: Performs data reads and writes for memory loads/stores (`ld`, `st`), stack manipulation (`push`, `pop`), and atomic swaps (`xchg`).
   * **Hardware Mapping**: Routes requests to **Port B** of the Dual-Port BSRAM (`0x0000–0xFEFF`) or across the Wishbone B4 interconnect for MMIO registers (`0xFF00–0xFFFF`).
   * **MPU & Privilege Enforcement**: Hardware checks memory writes against active `[MPU_BASE .. MPU_LIMIT]` bounds and blocks User-mode MMIO access. Violations suppress memory writes and trigger **Vector 3 (`MPU / MMIO Fault`)**.
   * **Context-Serializing `CPU_STATUS` Write**: If a store (`st`, `xchg`) writes to `CPU_STATUS` (`0xFF07`), hardware updates the status bits (`SP_MODE`, `MODE`, `IE`, etc.), flushes younger instructions in `IF`, `ID`, and `EX`, and redirects `PC` to `mem_pc + 1` so subsequent instructions are fetched and decoded under the new processor state.
   * **Atomic RMW (`xchg`) Latency**: Because `xchg Rd, [Rs]` requires two consecutive bus cycles (read phase followed by write phase) while maintaining bus lock (`wb_cyc_o = 1`), it asserts a **1-cycle hardware pipeline stall** in the `MEM` stage (freezing earlier stages `IF`, `ID`, and `EX`).

5. **WB (Write-Back)**:
   * **Operation**: Writes computed ALU/DSP results, memory read data (`ld`, `pop`), or link register return addresses (`call`, `callr`) into the destination register `Rd` in the register file (routing `r15` writes to `KSP` or `USP` using the instruction's pipeline-propagated `sp_bank` tag).
   * **Timing**: Operates synchronously at the rising edge of the clock with zero cycle delay.

---

### 2. Pipeline Hazards & Resolution

#### A. Data Hazards & Forwarding (Bypass) Unit
To avoid pipeline stalls when an instruction depends on the result of a preceding arithmetic or logic instruction, MARC-16 incorporates an **ALU Forwarding Unit**:
* **EX-to-EX Forwarding**: Forwards the ALU/DSP output from the `EX/MEM` pipeline register directly into the ALU input multiplexers of the `EX` stage (resolves dependencies between consecutive ALU instructions: distance = 1).
* **MEM-to-EX Forwarding**: Forwards memory read data or earlier ALU outputs from the `MEM/WB` pipeline register directly into ALU inputs in `EX` (resolves dependencies with distance = 2).
* **Throughput**: Consecutive ALU instructions execute at full throughput of **1 instruction per clock cycle** (CPI = 1.0) without bubble insertion.

#### B. Load-Use Delay (1-Cycle Hardware Interlock)
Because memory read data is only available at the end of the `MEM` stage (after Port B BSRAM read latency), an instruction in `ID` that requires data loaded by an immediately preceding `ld` or `pop` cannot be resolved solely via forwarding:
* **Interlock Condition**:
  $$(\text{ID\textunderscore{}reads\textunderscore{}Rs} \ \land \ (\text{ID\textunderscore{}Rs} == \text{EX\textunderscore{}Rd})) \quad \lor \quad (\text{ID\textunderscore{}reads\textunderscore{}Rd} \ \land \ (\text{ID\textunderscore{}Rd} == \text{EX\textunderscore{}Rd})) \quad (\text{when EX instruction is } ld \text{ or } pop)$$
* **Hardware Interlock Behavior**:
  * Hardware automatically freezes the `PC` and `IF/ID` pipeline registers for **1 clock cycle** (`stall`).
  * A bubble (`nop`) is injected into the `ID/EX` pipeline register.
  * In the subsequent clock cycle, loaded data from the `MEM` stage is forwarded directly to the `EX` stage without further delay.

#### C. Branch Penalty (2-Cycle Pipeline Flush)
When program control flow deviates from sequential execution:
* **Taken Branches & Jumps (`jz`, `jnz`, `jmp`, `call`, `jr`, `callr`, `reti`, `syscall`)**:
  * The branch condition and jump target are computed and resolved in the `EX` stage.
  * When a branch is taken, hardware asserts a **Pipeline Flush** signal.
  * Instructions in the `IF` and `ID` stages are cleared into bubbles (`nop`), incurring a **2-cycle branch penalty**.
  * **Untaken Branches**: Sequential fall-through conditional branches incur **0 penalty cycles**.

#### D. Atomic Read-Modify-Write Penalty (xchg 1-Cycle MEM Stall)
The `xchg Rd, [Rs]` instruction executes an indivisible Read-Modify-Write cycle on the shared bus:
* **Cycle 1 (`MEM` read phase)**: Reads existing word from `RAM[Rs]` across Port B / Wishbone bus into the write-back buffer.
* **Cycle 2 (`MEM` write phase)**: Writes new register data `Rd` to `RAM[Rs]` while keeping `wb_cyc_o` continuously asserted.
* **Pipeline Impact**: The execution of `xchg` incurs a hardware-enforced **1-cycle pipeline stall** in the `MEM` stage (freezing `IF`, `ID`, and `EX`), resulting in a 2-cycle latency for atomic swap operations without disturbing single-cycle pipelining for standard loads and stores.

#### E. Context-Serializing System Writes (`CPU_STATUS` Pipeline Flush)
Because `CPU_STATUS` (`0xFF07`) is written in the `MEM` stage while `SP_MODE` (bank selection for `r15` in `ID`) and `MODE` (privilege/MPU checks in `IF` and `ID`) affect earlier pipeline stages:
* Any write (`st`, `xchg`) to `CPU_STATUS` (`0xFF07`) acts as a **context-serializing operation**: when the write commits in `MEM`, hardware flushes the in-flight instructions in `IF`, `ID`, and `EX` into bubbles (`nop`) and restarts instruction fetch at `mem_pc + 1`.
* This guarantees that `mov r15, rX`, `push`, or `pop` placed immediately after a `CPU_STATUS` write always operates on the newly selected stack pointer (`KSP` or `USP`) without requiring manual `nop` instructions.

---

## System Interconnect & Wishbone B4 Bus Specification

The on-chip bus of the MARC-16 processor is based on the open **Wishbone B4 (Classic / Pipelined)** standard, adapted to a fixed 16-bit data and address width. The bus uses separate unidirectional read and write lines (no internal tri-state buffers), which maps directly onto the logic LUTs and block BSRAM of the Gowin GW2AR-18 (Tang Nano 20K).

---

### 1. Bus Signals

All address and data buses are 16 bits wide. Signals are synchronized to the rising edge of the system clock `wb_clk_i`.

| Signal | Direction (from the Master) | Width | Active level | Description |
| --- | --- | --- | --- | --- |
| `wb_clk_i` | Input | 1 | Edge $\uparrow$ | Common system clock (up to 50 MHz) |
| `wb_rst_i` | Input | 1 | High (`1`) | Synchronous hardware reset of the interconnect |
| `wb_adr_o` | Output | 16 | — | 16-bit memory or register address (`0x0000–0xFFFF`) |
| `wb_dat_o` | Output | 16 | — | Data sent from Master to Slave (write operations) |
| `wb_dat_i` | Input | 16 | — | Data received from Slave by the Master (read operations) |
| `wb_we_o` | Output | 1 | `1` = Write | Transfer direction: `1` — write (`st`, `push`), `0` — read (`ld`, `pop`) |
| `wb_sel_o` | Output | 2 | `1` | Byte select: `2'b11` (MARC-16 works with 16-bit words by default) |
| `wb_stb_o` | Output | 1 | High (`1`) | **Strobe**: indicates a valid address and selection of a specific Slave |
| `wb_cyc_o` | Output | 1 | High (`1`) | **Cycle**: active for the entire bus transaction cycle |
| `wb_ack_i` | Input | 1 | High (`1`) | **Acknowledge**: the Slave confirms a successful write or valid read data |
| `wb_err_i` | Input | 1 | High (`1`) | **Error**: hardware fault signal (MPU violation, MMIO access denied, or access to a nonexistent address) |

---

### 2. Bus Cycle Types and Protocols

#### A. Single-Cycle Transfer

For the fast internal BSRAM (`0x0000–0xFEFF`) and fast MMIO registers, the transfer completes with no wait states (zero-wait-state):

* **Cycle 1:** The Master drives `wb_adr_o` and `wb_we_o` and raises `wb_cyc_o = 1` and `wb_stb_o = 1`.
* **Cycle 2:** In the same or the next cycle the Slave asserts `wb_ack_i = 1` (and `wb_dat_i` on reads). The Master latches the result, after which `wb_cyc_o` and `wb_stb_o` drop to `0`.

```text
Clock      :   __    __    __    __
            __|  \__/  \__/  \__/  \__
wb_adr_o   : ----<  ADDR  >-----------
wb_we_o    : _____/‾‾‾‾‾‾‾‾‾\_________  (1 = Write, 0 = Read)
wb_cyc_o   : _____/‾‾‾‾‾‾‾‾‾\_________
wb_stb_o   : _____/‾‾‾‾‾‾‾‾‾\_________
wb_ack_i   : _____/‾‾‾‾‾‾‾‾‾\_________  (zero-wait response)
wb_dat_o/i : ----<  DATA  >-----------
                 Cycle 1  Cycle 2

```

#### B. Atomic Read-Modify-Write Cycle (`xchg`)

To execute `xchg Rd, [Rs]`, the **`wb_cyc_o` line stays active (`1`) through both phases** (reading the word, then writing the word):

```text
Clock    :   __    __    __    __    __
          __|  \__/  \__/  \__/  \__/  \__
wb_cyc_o : _____/‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾\_____  (held the whole time!)
wb_stb_o : _____/‾‾‾‾\_____/‾‾‾‾\_________  (two separate pulses)
wb_we_o  : ________________/‾‾‾‾\_________  (0 = Read, then 1 = Write)
wb_ack_i : _____/‾‾‾‾\_____/‾‾‾‾\_________
                Read         Write
```

Holding `wb_cyc_o = 1` guarantees to the bus arbiter that no other Master (for example the DMA) can take over memory access between the read phase and the write phase.

#### C. Hardware Access Error (`wb_err_i`)

If a CPU Master in User Mode (`MODE == 1`) writes outside the MPU bounds (`addr < MPU_BASE` or `addr > MPU_LIMIT` while `MPU_CTRL[0] == 1`), or tries to read or write registers in the MMIO window (`0xFF00–0xFFFF`):

1. The interconnect blocks the write `we` to memory/peripheral.
2. Instead of `wb_ack_i`, the signal **`wb_err_i = 1`** is asserted.
3. The processor aborts the current instruction, latches the address into `MPU_FAULT_ADDR` (`0xFF0B`), and traps to **Vector 3 (`0x0003`)**.

The DMA Master (M1) does not trap the CPU. Protection violations of a User-domain transfer are detected at `START` (see *Hardware protection and MPU interaction*) and reported as `DMA_STATUS[2]` (`ERR_MPU`). If `wb_err_i` is received while a transfer is running (for example an access to an unmapped MMIO slot), the channel is aborted and `DMA_STATUS[3]` (`ERR_ADDR`) is set. Both are signalled through IRQ 6 (`0x0016`) when `DMA_CTRL[1] == 1`.

---

### 3. Interconnect Topology and Bus Arbitration

The interconnect joins two request sources (Masters) and distributes access to the physical resources:

```text
                   ┌───────────────────────┐
                   │  MARC-16 CPU (M0)     │
                   └───────────┬───────────┘
                               │ Wishbone M0
                               ▼
                   ┌───────────────────────┐
  DMA (M1) ───────►│  Wishbone Arbiter     │◄── Priority (PRIO_EN: Stealing/Burst)
  (0xFF60)         └───────────┬───────────┘
                               │ Shared bus
                               ▼
                   ┌───────────────────────┐
                   │ Address Crossbar / MUX│◄── MPU block & MODE check
                   └───┬───────────────┬───┘
                       │               │
      wb_adr < 0xFF00  │               │ wb_adr >= 0xFF00 (0xFFxx)
                       ▼               ▼
             ┌────────────────┐     ┌────────────────────────────────┐
             │ Dual-Port      │     │ 16-slot MMIO Demultiplexer     │
             │ BSRAM (Port B) │     └──┬─────┬─────┬─────┬─────┬────┘
             └────────────────┘        │     │     │     │     │
                                      Sys  UART  GPIO   SPI/  DMA/
                                      (0x0)(0x1) (0x2)  I2C   PWM
                                                        (0x4/5)(0x6/7)

```

*Sys = Timer, Interrupt Controller, MPU, and CPU_USP (all in slot `0x0`).*

1. **Bus Arbiter (priority):**
   * **Cycle Stealing (`PRIO_EN = 0`):** The CPU has absolute priority. The DMA takes a step only when the CPU is not asserting `wb_stb_o`. If the CPU raises a request during a DMA transfer, the DMA pauses for 1 cycle.
   * **Burst Mode (`PRIO_EN = 1`):** The DMA gets uninterrupted bus access for the duration of the burst. If the CPU tries to access Port B, the bus asserts the internal CPU stall signal (`cpu_stall`).
2. **MMIO Address Decoding:**
   * MMIO window check: `is_mmio = (wb_adr_o[15:8] == 8'hFF)`.
   * Peripheral slot select: `slot_sel = wb_adr_o[7:4]` (16 slots of 16 words).
   * Internal offset: `reg_offset = wb_adr_o[3:0]` (maps onto the 4-bit offset of `ld`/`st` instructions).



---

## Target Hardware Profile (`Tang Nano 20K`)

| Resource / Parameter | Specification |
| --- | --- |
| **Target FPGA** | Gowin **GW2AR-LV18QN88C8/I7** (Sipeed Tang Nano 20K) |
| **Core Logic Utilization** | ~1,200 LUT4 (~5.8% of 20,736 LUTs) & ~400 Flip-Flops (~2%) |
| **Hardware Multiplier** | 1 × Gowin `MULT18X18` DSP slice (0 LUT overhead for `mul`/`mulh`/`mlhu`) |
| **Memory Subsystem** | True Dual-Port BSRAM (Port A: Instruction Fetch, Port B: Data/Stack R/W) |
| **Internal Bus** | Wishbone B4, 16-bit; Masters: CPU (M0) and DMA (M1) |
| **System Clock (max)** | 50 MHz nominal (synthesizes up to 75–85 MHz with Gowin EDA / Yosys+nextpnr) |
