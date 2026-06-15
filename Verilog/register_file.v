module register_file (
    input wire clk,

    input wire we_h,

    input wire rst,

    input wire [1:0] command,

    input wire movb,
    input wire [1:0] movb_bank_sel1,
    input wire [1:0] movb_bank_sel2,

    input wire [2:0] reg1_sel,
    input wire [2:0] reg2_sel,
    input wire [2:0] reg3_sel,

    input wire [1:0] shift_type,
    input wire [3:0] shift_mag,

    input wire [7:0] data,

    input wire [15:0] alu_res,
    input wire [15:0] ram_data_out,

    input wire        mul_we,
    input wire [15:0] mul_hi,
    input wire [15:0] mul_lo,

    input wire setf_we,
    input wire flags_we,
    input wire [15:0] flags_in,

    input wire sys_r,
    input wire [1:0] sys_sel,
    input wire [2:0] sys_rg_sel,

    output wire [15:0] output_reg1,
    output wire [15:0] output_reg2,
    output wire [15:0] output_reg3,

    output wire [15:0] output_flags
);

    reg [15:0] registers [3:0][7:0];
    reg [15:0] flags;
    reg [15:0] PC;
    reg [15:0] SC;

    wire [15:0] result_in;

    wire [1:0] bank_sel = flags[6:5];

    wire [15:0] bus_out;
    wire [15:0] bus_in;

    assign result_in = (command == 2'b10) ? ram_data_out : alu_res;

    assign bus_in = registers[bank_sel][reg1_sel];

    shifter bus_shifter(.data_in(bus_in), .shift_m(shift_mag), .shift_t(shift_type), .data_out(bus_out));

    integer i, j;

    always @(posedge clk) begin
        if (rst) begin
            flags <= 16'h0000;
            for (j = 0; j < 4; j = j + 1)begin
                for (i = 0; i < 8; i = i + 1) begin
                    registers[j][i] <= 16'h0000;

                end
            end
        end else begin
            case(command)
                    2'b00: registers[bank_sel][reg3_sel] <= bus_out;

                    2'b10: registers[bank_sel][reg3_sel] <= result_in;

                    2'b11: begin
                        if (we_h) registers[bank_sel][reg3_sel][15:8] <= data;

                        else registers[bank_sel][reg3_sel][7:0]  <= data;

                    end
                    default: ;
            endcase

            if (mul_we) begin
                registers[2][0] <= mul_lo;
                registers[2][1] <= mul_hi;
            end

            if (movb) registers[movb_bank_sel2][reg3_sel] <= registers[movb_bank_sel1][reg1_sel];


            if (setf_we) flags <= registers[bank_sel][reg1_sel];
            else if (flags_we) flags <= flags_in;
        end
    end

    assign output_reg1 = registers[bank_sel][reg1_sel];
    assign output_reg2 = registers[bank_sel][reg2_sel];
    assign output_reg3 = registers[bank_sel][reg3_sel];
    assign output_flags = flags;

endmodule

module shifter (
    input wire [15:0] data_in,
    input wire [3:0] shift_m,
    input wire [1:0] shift_t,

    output reg [15:0] data_out
);

    always@(*) begin
        case (shift_t)
            2'b00: data_out = data_in;
            2'b01: data_out = data_in << shift_m;
            2'b10: data_out = data_in >> shift_m;
            2'b11: data_out = $signed(data_in) >>> shift_m;
            default: data_out = data_in;

        endcase
    end
endmodule
