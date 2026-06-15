`timescale 1ns / 1ps

// ============================================================================
// Testbench for cpu module
//
// Instruction encoding (16-bit command):
//
//  [1:0] = 2'b00  — register file ops; subtype in [3:2]:
//      2'b00  COPY/SHIFT  src=reg1[6:4], dst=reg3[9:7],
//                         shift_mag[13:10], shift_type[15:14]
//      2'b01  (reg2_sel=[6:4], reg1_sel=[9:7], no write)
//      2'b10  (reg3[9:7] ← alu_res / ram_data_out)
//      2'b11  LOAD IMM    we_h=[4], data=[12:5],
//                         reg3_sel={1'b0, command[15:14]}  (r0–r3 only)
//
//  [1:0] = 2'b01  — ALU ops; alu_cmd in [5:2]:
//      default  reg1=[8:6], reg2=[11:9]
//      4'b1110  SETF  setf_we=1, reg1=[8:6]
//      4'b1101  GETF  (no reg fields)
//
// NOTE: output_reg1/reg2/reg3/flags ports of register_file are NOT
// connected inside cpu.v, so arg1/arg2/flags_in of the ALU are always
// high-Z.  ALU arithmetic results are therefore undefined; only control-
// signal decoding and side effects via mul_we / setf_we are verified.
// ============================================================================

module cpu_tb;

// ── DUT ─────────────────────────────────────────────────────────────────────
reg        clk;
reg        rst;
reg [15:0] command;

cpu dut (
    .clk    (clk),
    .rst    (rst),
    .command(command)
);

// ── Clock (100 MHz / 10 ns period) ──────────────────────────────────────────
initial clk = 0;
always  #5 clk = ~clk;

// ── Counters ─────────────────────────────────────────────────────────────────
integer pass_cnt;
integer fail_cnt;

// ── Hierarchical shortcuts ───────────────────────────────────────────────────
`define R(b,r)  dut.rf.registers[(b)][(r)]
`define FLAGS    dut.rf.flags

// ── Verify task (16-char label max) ─────────────────────────────────────────
task chk;
    input [15:0]     got;
    input [15:0]     expected;
    input [8*16-1:0] label;
    begin
        if (got === expected) begin
            $display("PASS  %-16s  val=%04h", label, got);
            pass_cnt = pass_cnt + 1;
        end else begin
            $display("FAIL  %-16s  got=%04h  exp=%04h", label, got, expected);
            fail_cnt = fail_cnt + 1;
        end
    end
endtask

// ── Instruction builders ─────────────────────────────────────────────────────
// LOAD IMM LOW:  {r[1:0], 1'b0, imm[7:0], 1'b0, 2'b11, 2'b00}
// LOAD IMM HIGH: {r[1:0], 1'b0, imm[7:0], 1'b1, 2'b11, 2'b00}
// COPY/SHIFT:    {stype[1:0], smag[3:0], dst[2:0], src[2:0], 2'b00, 2'b00}
// ALU:           {4'b0, r2[2:0], r1[2:0], cmd[3:0], 2'b01}

function [15:0] LOADI_L;
    input [1:0] r;
    input [7:0] imm;
    LOADI_L = {r, 1'b0, imm, 1'b0, 2'b11, 2'b00};
endfunction

function [15:0] LOADI_H;
    input [1:0] r;
    input [7:0] imm;
    LOADI_H = {r, 1'b0, imm, 1'b1, 2'b11, 2'b00};
endfunction

function [15:0] COPY;
    input [2:0] src;
    input [2:0] dst;
    COPY = {2'b00, 4'b0000, dst, src, 2'b00, 2'b00};
endfunction

function [15:0] SHIFT;
    input [2:0] src;
    input [2:0] dst;
    input [1:0] stype;   // 00=none, 01=LSL, 10=LSR, 11=ASR
    input [3:0] smag;
    SHIFT = {stype, smag, dst, src, 2'b00, 2'b00};
endfunction

function [15:0] ALU;
    input [3:0] cmd;
    input [2:0] r1;
    input [2:0] r2;
    ALU = {4'b0000, r2, r1, cmd, 2'b01};
endfunction

// ── One-cycle step ───────────────────────────────────────────────────────────
task tick;
    begin
        @(posedge clk); #1;
    end
endtask

// ── Timeout ──────────────────────────────────────────────────────────────────
initial begin
    #10000;
    $display("TIMEOUT");
    $finish;
end

// ── Stimulus ─────────────────────────────────────────────────────────────────
initial begin
    $dumpfile("cpu_tb.vcd");
    $dumpvars(0, cpu_tb);

    pass_cnt = 0;
    fail_cnt = 0;
    command  = 16'h0;
    rst      = 1;

    // ── 1. Reset ─────────────────────────────────────────────────────────────
    repeat (3) tick;
    rst = 0;
    #1;

    $display("-- Reset -----------------------------------");
    chk(`R(0,0), 16'h0000, "rst r0");
    chk(`R(0,1), 16'h0000, "rst r1");
    chk(`R(0,2), 16'h0000, "rst r2");
    chk(`R(0,3), 16'h0000, "rst r3");
    chk(`FLAGS,  16'h0000, "rst flags");

    // ── 2. LOAD IMMEDIATE ────────────────────────────────────────────────────
    $display("-- Load immediate --------------------------");

    // r0[7:0] <- 0xAB
    command = LOADI_L(2'd0, 8'hAB); tick;
    chk(`R(0,0), 16'h00AB, "load_lo r0=AB");

    // r0[15:8] <- 0xCD  =>  r0 = 0xCDAB
    command = LOADI_H(2'd0, 8'hCD); tick;
    chk(`R(0,0), 16'hCDAB, "load_hi r0=CDAB");

    // r1 = 0x0034
    command = LOADI_L(2'd1, 8'h34); tick;
    chk(`R(0,1), 16'h0034, "load_lo r1=34");

    // r2 = 0x0002
    command = LOADI_L(2'd2, 8'h02); tick;
    chk(`R(0,2), 16'h0002, "load_lo r2=02");

    // r3 = 0x00FF
    command = LOADI_L(2'd3, 8'hFF); tick;
    chk(`R(0,3), 16'h00FF, "load_lo r3=FF");

    // ── 3. COPY (no shift) ───────────────────────────────────────────────────
    $display("-- Copy / shift ----------------------------");

    // r4 <- r0  (no shift)
    command = COPY(3'd0, 3'd4); tick;
    chk(`R(0,4), 16'hCDAB, "copy r0->r4");

    // ── 4. SHIFT LEFT ────────────────────────────────────────────────────────
    // r5 <- r0 << 4 = 0xCDAB << 4 = 0xDAB0
    command = SHIFT(3'd0, 3'd5, 2'b01, 4'd4); tick;
    chk(`R(0,5), 16'hDAB0, "lsl4 r0->r5");

    // ── 5. LOGICAL SHIFT RIGHT ───────────────────────────────────────────────
    // r6 <- r0 >> 4 = 0xCDAB >> 4 = 0x0CDA
    command = SHIFT(3'd0, 3'd6, 2'b10, 4'd4); tick;
    chk(`R(0,6), 16'h0CDA, "lsr4 r0->r6");

    // ── 6. ARITHMETIC SHIFT RIGHT ────────────────────────────────────────────
    // r7 <- r0 >>> 4  (0xCDAB has bit15=1, so sign-extended)
    // 0xCDAB >>> 4 = 0xFCDA
    command = SHIFT(3'd0, 3'd7, 2'b11, 4'd4); tick;
    chk(`R(0,7), 16'hFCDA, "asr4 r0->r7");

    // ── 7. Copy r3 to r0 (overwrite for next group) ──────────────────────────
    command = COPY(3'd3, 3'd0); tick;
    chk(`R(0,0), 16'h00FF, "copy r3->r0");

    // Shift by 0 must be identity
    command = SHIFT(3'd0, 3'd0, 2'b01, 4'd0); tick;
    chk(`R(0,0), 16'h00FF, "lsl0 r0->r0");

    // ── 8. SETF — load flags from a register ────────────────────────────────
    // Must be done before any ALU op: ALU ops with floating arg1/arg2 assert
    // flags_we=1 and corrupt flags to X (unconnected output_reg ports in cpu.v).
    // Load r1 with 0x0003; bank_sel bits [6:5] are 0 → stays in bank 0.
    $display("-- SETF ----------------------------------------");
    command = LOADI_L(2'd1, 8'h03); tick;
    chk(`R(0,1), 16'h0003, "pre-setf r1=03");

    // SETF: [1:0]=01, [5:2]=1110, [8:6]=001 (r1)
    // Side effect: reg_command=2'b00 also writes r1 into r0 (reg3_sel=0 default).
    command = {4'b0000, 3'b000, 3'b001, 4'b1110, 2'b01}; tick;
    chk(`FLAGS, 16'h0003, "setf flags=03");

    // ── 9. GETF — alu_on=1, alu_cmd=1101, no flags update ───────────────────
    $display("-- GETF ----------------------------------------");
    command = ALU(4'b1101, 3'd0, 3'd0); #1;
    if (dut.alu_on === 1'b1 && dut.alu_command === 4'b1101) begin
        $display("PASS  getf_decode  alu_on=1 cmd=1101");
        pass_cnt = pass_cnt + 1;
    end else begin
        $display("FAIL  getf_decode  alu_on=%b cmd=%04b",
                 dut.alu_on, dut.alu_command);
        fail_cnt = fail_cnt + 1;
    end
    tick;
    chk(`FLAGS, 16'h0003, "getf no flag chg");

    // ── 10. ALU instruction decode ───────────────────────────────────────────
    // output_reg1/reg2 are floating in cpu.v, so arithmetic results and
    // flags_out are undefined after these ops — only control signals verified.
    $display("-- ALU decode (control signals only) ------");

    // ADD
    command = ALU(4'b1000, 3'd0, 3'd1); #1;
    if (dut.alu_on === 1'b1 && dut.alu_command === 4'b1000) begin
        $display("PASS  alu_add_decode  alu_on=1 cmd=1000");
        pass_cnt = pass_cnt + 1;
    end else begin
        $display("FAIL  alu_add_decode  alu_on=%b cmd=%04b",
                 dut.alu_on, dut.alu_command);
        fail_cnt = fail_cnt + 1;
    end
    tick;

    // AND
    command = ALU(4'b0000, 3'd0, 3'd1); #1;
    if (dut.alu_on === 1'b1 && dut.alu_command === 4'b0000) begin
        $display("PASS  alu_and_decode  alu_on=1 cmd=0000");
        pass_cnt = pass_cnt + 1;
    end else begin
        $display("FAIL  alu_and_decode  alu_on=%b cmd=%04b",
                 dut.alu_on, dut.alu_command);
        fail_cnt = fail_cnt + 1;
    end
    tick;

    // SUB
    command = ALU(4'b1001, 3'd0, 3'd1); #1;
    if (dut.alu_on === 1'b1 && dut.alu_command === 4'b1001) begin
        $display("PASS  alu_sub_decode  alu_on=1 cmd=1001");
        pass_cnt = pass_cnt + 1;
    end else begin
        $display("FAIL  alu_sub_decode  alu_on=%b cmd=%04b",
                 dut.alu_on, dut.alu_command);
        fail_cnt = fail_cnt + 1;
    end
    tick;

    // ── 11. MUL/DIV — mul_we must be asserted combinationally ────────────────
    $display("-- MUL mul_we ----------------------------------");
    command = ALU(4'b0110, 3'd1, 3'd2); #1;
    if (dut.mul_we === 1'b1) begin
        $display("PASS  mul_we=1");
        pass_cnt = pass_cnt + 1;
    end else begin
        $display("FAIL  mul_we=%b (expected 1)", dut.mul_we);
        fail_cnt = fail_cnt + 1;
    end
    tick;

    // DIV — mul_we also used for quotient/remainder
    command = ALU(4'b0111, 3'd1, 3'd2); #1;
    if (dut.mul_we === 1'b1) begin
        $display("PASS  div_mul_we=1");
        pass_cnt = pass_cnt + 1;
    end else begin
        $display("FAIL  div_mul_we=%b (expected 1)", dut.mul_we);
        fail_cnt = fail_cnt + 1;
    end
    tick;

    // Non-MUL op must NOT assert mul_we
    command = ALU(4'b1000, 3'd0, 3'd1); #1;
    if (dut.mul_we === 1'b0) begin
        $display("PASS  add_mul_we=0");
        pass_cnt = pass_cnt + 1;
    end else begin
        $display("FAIL  add_mul_we=%b (expected 0)", dut.mul_we);
        fail_cnt = fail_cnt + 1;
    end
    tick;

    // ── 12. Second reset clears everything ────────────────────────────────────
    $display("-- Second reset --------------------------------");
    rst = 1; repeat(2) tick; rst = 0; #1;
    chk(`R(0,0), 16'h0000, "rst2 r0");
    chk(`R(0,4), 16'h0000, "rst2 r4");
    chk(`R(0,7), 16'h0000, "rst2 r7");
    chk(`FLAGS,  16'h0000, "rst2 flags");

    // ── Summary ──────────────────────────────────────────────────────────────
    $display("================================================");
    if (fail_cnt == 0)
        $display("ALL PASSED  (%0d tests)", pass_cnt);
    else
        $display("RESULTS  %0d passed  %0d FAILED", pass_cnt, fail_cnt);

    $finish;
end

endmodule
