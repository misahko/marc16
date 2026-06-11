`timescale 1ns / 1ps // Задаємо одиницю часу (1 наносекунда)

module register_file_tb;

    // 1. Оголошуємо сигнали, які підключимо до входів модуля (регістри reg)
    reg clk;
    reg we_h;
    reg [1:0] command;
    reg [1:0] bank_sel;
    reg [2:0] reg1_sel;
    reg [2:0] reg2_sel;
    reg [2:0] reg3_sel;
    reg [1:0] shift_type;
    reg [3:0] shift_mag;
    reg [7:0] data;
    reg [15:0] ram_input;

    // 2. Оголошуємо дроти для виходів модуля (wire)
    wire [15:0] output_reg1;
    wire [15:0] output_reg2;
    wire [15:0] output_reg3;

    // 3. Створюємо екземпляр нашого регістрового файлу (UUT - Unit Under Test)
    register_file uut (
        .clk(clk),
        .we_h(we_h),
        .command(command),
        .bank_sel(bank_sel),
        .reg1_sel(reg1_sel),
        .reg2_sel(reg2_sel),
        .reg3_sel(reg3_sel),
        .shift_type(shift_type),
        .shift_mag(shift_mag),
        .data(data),
        .ram_input(ram_input),
        .output_reg1(output_reg1),
        .output_reg2(output_reg2),
        .output_reg3(output_reg3)
    );

    // 4. Генератор тактового сигналу (clk) — змінює стан кожні 5 нс (період 10 нс)
    always #5 clk = ~clk;

    // 5. Головний блок тестування
    initial begin
        // Створюємо файл для збереження хвильових діаграм (для GTKWave)
        $dumpfile("register_file_test.vcd");
        $dumpvars(0, register_file_tb);

        // Початкова ініціалізація сигналів
        clk = 0;
        we_h = 0;
        command = 2'b11; // почнемо з команди 2'b11 (запис байта)
        bank_sel = 2'b00; // працюємо з BANK0
        reg1_sel = 0; reg2_sel = 0; reg3_sel = 0;
        shift_type = 0; shift_mag = 0;
        data = 0; ram_input = 0;

        #10; // Чекаємо 10 нс

        // === ТЕСТ 1: Запис числа 0x55 у нижній байт REG2 (Команда 2'b11, L) ===
        $display("Test 1: Writing 0x55 to lower byte of REG2...");
        command = 2'b11;
        we_h = 0;         // L = 0 (нижній байт)
        reg2_sel = 3'd2;  // вибираємо REG2
        data = 8'h01;     // дані 0x55
        #10;              // Чекаємо один такт

        // === ТЕСТ 2: Запис числа 0xAA у верхній байт REG2 (Команда 2'b11, H) ===
        $display("Test 2: Writing 0xAA to upper byte of REG2...");
        we_h = 1;         // H = 1 (верхній байт)
        data = 8'h00;     // дані 0xAA
        #10;              // Тепер в REG2 має лежати повне число 0xAA55

        // === ТЕСТ 3: Копіювання з REG2 в REG4 з логічним зсувом ліворуч на 2 (Команда 2'b00, MOV) ===
        $display("Test 3: MOV REG2 to REG4 with LSL by 2...");
        command = 2'b00;      // Команда MOV
        reg1_sel = 3'd2;      // Джерело (FROM) = REG2 (там лежить 0xAA55)
        reg2_sel = 3'd4;      // Куди (TO) = REG4
        shift_type = 2'b01;   // Логічний зсув ліворуч (<<)
        shift_mag = 4'd2;     // Величина зсуву = 2
        #10;

        $display(uut.registers[0][2], uut.registers[0][4]);


        command = 2'b00;      // Команда MOV
        reg1_sel = 3'd2;      // Джерело (FROM) = REG2 (там лежить 0xAA55)
        reg2_sel = 3'd2;      // Куди (TO) = REG4
        shift_type = 2'b01;   // Логічний зсув ліворуч (<<)
        shift_mag = 4'd1;     // Величина зсуву = 2
        #10;
        $display(uut.registers[0][2]);
        // === ТЕСТ 4: Завантаження даних з RAM у REG3 (Команда 2'b10, LOAD) ===
        $display("Test 4: LOAD from RAM to REG3...");
        command = 2'b10;      // Команда LOAD
        reg3_sel = 3'd3;      // Цільовий регістр = REG3
        ram_input = 16'h1234; // Дані, які нібито прийшли з RAM
        #10;

        // === ТЕСТ 5: Перевірка читання через вихідні порти ===
        $display("Test 5: Verification of output ports...");
        command = 2'b01;      // Перемикаємо команду в режим спокою
        reg1_sel = 3'd2;      // На output_reg1 маємо побачити REG2 (0xAA55)
        reg2_sel = 3'd4;      // На output_reg2 маємо побачити REG4 (результат зсуву)
        reg3_sel = 3'd3;      // На output_reg3 маємо побачити REG3 (0x1234 з RAM)
        #10;

        $display("Test 6: STORE");
        command = 2'b01;
        reg2_sel = 3'd2;
        reg3_sel = 3'd2;
        #10

        // Завершення симуляції
        $display("Simulation finished successfully!");
        $finish;
    end

endmodule