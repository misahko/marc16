module alu(
    input wire on,
    input  wire [3:0]  command,

    input  wire [15:0] arg1,
    input  wire [15:0] arg2,

    input  wire [15:0] flags_in,


    output reg         mul_we,
    output reg  [15:0] mul_hi,
    output reg  [15:0] mul_lo,

    output reg  [15:0] res,

    output reg         flags_we,
    output wire [15:0] flags_out   // нові флаги
);

wire [31:0] mul_result = arg1 * arg2;

wire        div_zero   = (arg2 == 16'h0);
wire [15:0] div_result = div_zero ? 16'h0 : arg1 / arg2;
wire [15:0] mod_result = div_zero ? 16'h0 : arg1 % arg2;

reg [16:0] bus;

always @(*) begin
    bus    = 17'h0;
    mul_we = 1'b0;
    flags_we = 1'b0;
    mul_hi = 16'h0;
    mul_lo = 16'h0;
    
    if (on) begin
        flags_we = command != 4'b1111 & command != 4'b1101 ? 1 : 0;
        
        case (command)
            4'b0000: bus = {1'b0, arg1 & arg2};
            4'b0001: bus = {1'b0, ~(arg1 & arg2)};
            4'b0010: bus = {1'b0, ~(arg1 | arg2)};
            4'b0011: bus = {1'b0, arg1 | arg2};
            4'b0100: bus = {1'b0, arg1 ^ arg2};
            4'b0101: bus = {1'b0, ~(arg1 ^ arg2)};
            4'b0110: begin                          // MUL
                mul_lo = mul_result[15:0];
                mul_hi = mul_result[31:16];
                mul_we = 1'b1;
            end
            4'b0111: begin                          // DIV
                mul_lo = div_result;
                mul_hi = mod_result;
                mul_we = 1'b1;
            end
            4'b1000: bus = arg1 + arg2;
            4'b1001: bus = arg1 - arg2;
            4'b1010: bus = arg1 + arg2 + flags_in[0];
            4'b1011: bus = arg1 - arg2 - flags_in[0];
            4'b1100: bus = arg1 - arg2;             // CMP
            4'b1101: bus = {1'b0, flags_in};        // GETF
            default: bus = 17'h0;
        endcase

        res = bus[15:0];
    end
end

ch_flags flag_calc(
    .command     (command),
    .data_in     (bus),
    .flags_in    (flags_in),
    .arg1_sign   (arg1[15]),
    .arg2_sign   (arg2[15]),
    .div_by_zero (div_zero),
    .mul_hi_bits (mul_result[31:16]),
    .div_res_bits(div_result),
    .is_add      (command == 4'b1000 || command == 4'b1010),
    .is_sub      (command == 4'b1001 || command == 4'b1011 ||
                  command == 4'b1100),
    .flags_out   (flags_out)
);

endmodule

module ch_flags(
    input  wire        arg1_sign,
    input  wire        arg2_sign,
    input  wire        is_add,
    input  wire        is_sub,
    input  wire        div_by_zero,
    input  wire [3:0]  command,
    input  wire [15:0] flags_in,
    input  wire [16:0] data_in,
    input  wire [15:0] mul_hi_bits,
    input  wire [15:0] div_res_bits,
    output reg  [15:0] flags_out
);

always @(*) begin
    flags_out = flags_in;

    case (command)
        4'b0110: begin                              // MUL
            flags_out[0] = (mul_hi_bits != 16'h0); // CF
            flags_out[1] = (mul_hi_bits == 16'h0) && (data_in[15:0] == 16'h0); // ZF
            flags_out[2] = data_in[15];             // SF
            flags_out[3] = 1'b0;                    // OF
        end

        4'b0111: begin                              // DIV
            flags_out[0] = div_by_zero;             // CF
            flags_out[1] = (div_res_bits == 16'h0); // ZF
            flags_out[2] = div_res_bits[15];        // SF
            flags_out[3] = 1'b0;                    // OF
        end

        4'b1101: ;                                  // GETF — не змінюємо
        4'b1110: ;                                  // SETF — не змінюємо
        4'b1111: ;                                  // NOP  — не змінюємо

        default: begin
            flags_out[1] = (data_in[15:0] == 16'h0); // ZF
            flags_out[2] = data_in[15];               // SF

            if (is_add) begin
                flags_out[0] = data_in[16];
                flags_out[3] = (arg1_sign == arg2_sign) && (data_in[15] != arg1_sign);

            end else if (is_sub) begin
                flags_out[0] = ~data_in[16];
                flags_out[3] = (arg1_sign != arg2_sign) && (data_in[15] != arg1_sign);

            end else begin
                flags_out[0] = 1'b0;
                flags_out[3] = 1'b0;

            end
        end
    endcase
end

endmodule