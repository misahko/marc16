module cpu(
    input wire clk,
    input wire rst,
    input wire [15:0] command
);
    wire we_h;
    wire movb;
    wire [1:0] movb_bank_sel1;
    wire  [1:0] movb_bank_sel2;
    wire  [1:0] reg_command;

    wire  [2:0] reg1_sel;
    wire  [2:0] reg2_sel;
    wire  [2:0] reg3_sel;

    wire  [1:0] shift_type;
    wire  [3:0] shift_mag;

    wire  [7:0] data;

    wire  setf_we;

    wire   [3:0]  alu_command;
    wire  alu_on;
    wire [15:0] alu_res;

    wire [15:0] ram_data_out;

    wire        mul_we;
    wire [15:0] mul_hi;
    wire [15:0] mul_lo;

    wire        flags_we;
    wire [15:0] flags;

    wire [15:0] output_reg1;
    wire [15:0] output_reg2;
    wire [15:0] output_reg3;

    wire [15:0] output_flags;


    instruction_decoder id(
        .command(command),
        .we_h(we_h),

        .movb(movb),
        .movb_bank_sel1(movb_bank_sel1),
        .movb_bank_sel2(movb_bank_sel2),

        .reg_command(reg_command),
        .reg1_sel(reg1_sel),
        .reg2_sel(reg2_sel),
        .reg3_sel(reg3_sel),

        .shift_type(shift_type),
        .shift_mag(shift_mag),

        .data(data),

        .setf_we(setf_we),

        .alu_command(alu_command),
        .alu_on(alu_on)
    );

    register_file rf(
        .clk(clk),

        .we_h(we_h),

        .rst(rst),

        .command(reg_command),

        .movb(movb),
        .movb_bank_sel1(movb_bank_sel1),
        .movb_bank_sel2(movb_bank_sel2),

        .reg1_sel(reg1_sel),
        .reg2_sel(reg2_sel),
        .reg3_sel(reg3_sel),

        .shift_type(shift_type),
        .shift_mag(shift_mag),

        .data(data),

        .alu_res(alu_res),
        .ram_data_out(ram_data_out),

        .mul_we(mul_we),
        .mul_hi(mul_hi),
        .mul_lo(mul_lo),

        .setf_we(setf_we),
        .flags_we(flags_we),
        .flags_in(flags),

        .output_reg1(output_reg1),
        .output_reg2(output_reg2),
        .output_reg3(output_reg3)

    );

    alu alu(
        .on(alu_on),
        .command(alu_command),

        .arg1(output_reg1),
        .arg2(output_reg2),

        .flags_in(output_flags),


        .mul_we(mul_we),
        .mul_hi(mul_hi),
        .mul_lo(mul_lo),

        .res(alu_res),

        .flags_we(flags_we),
        .flags_out(flags)
    );


endmodule
