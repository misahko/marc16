module alu(
    input  wire        clk,
    input  wire [3:0]  command,
    input  wire [15:0] arg1,
    input  wire [15:0] arg2,
    output reg         mul_we,
    output reg  [15:0] mul_hi,
    output reg  [15:0] mul_lo,
    output reg  [15:0] res,
    output reg  [15:0] flags
);

wire [31:0] mul_result = arg1 * arg2;
wire [15:0] div_result = (arg2 != 0) ? arg1 / arg2 : 16'h0;
wire [15:0] mod_result = (arg2 != 0) ? arg1 % arg2 : 16'h0;

reg  [16:0] bus;
wire [15:0] next_flags;

always @(*) begin
    // default щоб уникнути latch
    bus = 17'h0;

    case (command)
        4'b0000: bus = {1'b0, arg1 & arg2};
        4'b0001: bus = {1'b0, ~(arg1 & arg2)};
        4'b0010: bus = {1'b0, ~(arg1 | arg2)};
        4'b0011: bus = {1'b0, arg1 | arg2};
        4'b0100: bus = {1'b0, arg1 ^ arg2};
        4'b0101: bus = {1'b0, ~(arg1 ^ arg2)};
        4'b1000: bus = arg1 + arg2;
        4'b1001: bus = arg1 - arg2;
        4'b1010: bus = arg1 + arg2 + flags[0];
        4'b1011: bus = arg1 - arg2 - flags[0];
        4'b1100: bus = arg1 - arg2;           // CMP
        4'b1101: bus = {1'b0, flags};         // GETF
        // MUL DIV SETF NOP — bus не потрібен, залишається 0
    endcase
end

ch_flags flag_calculation(
    .command   (command),
    .data_in   (bus),
    .flags_in  (flags),
    .arg1_sign (arg1[15]),
    .arg2_sign (arg2[15]),
    .is_add    (command == 4'b1000 || command == 4'b1010),
    .is_sub    (command == 4'b1001 || command == 4'b1011 ||
                command == 4'b1100),
    .flags_out (next_flags)
);

always @(posedge clk) begin
    mul_we <= 1'b0;

    case (command)
        4'b0110: begin         
            mul_lo <= mul_result[15:0];
            mul_hi <= mul_result[31:16];
            mul_we <= 1'b1;
        end

        4'b0111: begin     
            mul_lo <= div_result;  
            mul_hi <= mod_result; 
            mul_we <= 1'b1;
        end

        4'b1110:              
            flags <= arg1;

        default:
            flags <= next_flags;
    endcase

    res <= bus[15:0];
end

endmodule

module ch_flags(

    input arg1_sign,
    input arg2_sign,
    input is_add,
    input is_sub,

    input [3:0] command,

    input [15:0] flags_in,

    input [16:0] data_in,

    output reg [15:0] flags_out
);

    always @(*) begin
        flags_out = flags_in; 
        if (command != 4'b1110) begin
            flags_out[1] = (data_in[15:0] == 16'h0000);

            flags_out[2] = data_in[15];

            if (is_add) begin
                flags_out[0] = data_in[16]; 
                flags_out[3] = (arg1_sign == arg2_sign) && (data_in[15] != arg1_sign);
            end 
            else if (is_sub) begin
                flags_out[0] = ~data_in[16]; 
                    
                flags_out[3] = (arg1_sign != arg2_sign) && (data_in[15] != arg1_sign);
            end 
            else begin
                flags_out[0] = 1'b0;
                flags_out[3] = 1'b0;
            end
        end
    end

endmodule