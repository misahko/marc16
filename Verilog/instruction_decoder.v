module instruction_decoder(
    input wire [15:0] command,

    output reg we_h,
    output reg movb,
    output reg [1:0] movb_bank_sel1,
    output reg  [1:0] movb_bank_sel2,
    output reg  [1:0] reg_command,

    output reg  [2:0] reg1_sel,
    output reg  [2:0] reg2_sel,
    output reg  [2:0] reg3_sel,

    output reg  [1:0] shift_type,
    output reg  [3:0] shift_mag,

    output reg  [7:0] data,

    output reg  setf_we,

    output reg   [3:0]  alu_command,
    output reg  alu_on

);

    always@(*) begin
        we_h = 1'b0;
        movb = 1'b0;
        setf_we = 1'b0;
        alu_on = 1'b0;
        movb_bank_sel1 = 2'b0;
        movb_bank_sel2 = 2'b0;
        reg_command = 2'b0;
        reg1_sel = 3'b0;
        reg2_sel = 3'b0;
        reg3_sel = 3'b0;
        shift_type = 2'b0;
        shift_mag = 4'b0;
        data = 8'b0;
        alu_command = 4'b0;

        case(command[1:0])
            2'b00: begin
                alu_on = 1'b0;
                reg_command = command[3:2];

                case(reg_command)
                    2'b00: begin

                        reg1_sel = command[6:4];
                        reg3_sel = command[9:7];

                        shift_mag = command[13:10];
                        shift_type = command[15:14];
                    end

                    2'b01: begin
                        reg2_sel = command[6:4];
                        reg1_sel = command[9:7];
                    end

                    2'b10: begin
                        reg2_sel = command[6:4];
                        reg3_sel = command[9:7];
                    end

                    2'b11: begin
                        we_h = command[4];

                        data = command[12:5];

                        reg3_sel = command[15:13];
                    end
                endcase

            end

            2'b01: begin
                alu_on = 1'b1;
                alu_command = command[5:2];

                case(alu_command)
                    4'b1101: ;
                    4'b1110: begin
                        setf_we = 1'b1;
                        reg1_sel = command[8:6];
                    end
                    default: begin
                        reg1_sel = command[8:6];
                        reg2_sel = command[11:9];
                    end

                endcase

            end
        endcase
    end

endmodule
