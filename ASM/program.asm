; Програма: підрахунок суми чисел від 1 до 5
main:
    clr  r1             ; r1 = sum = 0
    li16 r2, 1024          ; r2 = counter = 5

loop:
    add  r1, r2         ; sum += counter
    dec  r2             ; counter--
    jnz  r2, loop       ; якщо counter != 0, повторюємо

    wfi                 ; зупинка процесора
