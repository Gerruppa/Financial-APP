# Historia zmian

## Nieopublikowane

### Nowe funkcje
- Okno transakcji jeszcze przed zapisem podpowiada, gdy na koncie zabraknie gotówki na zakup lub wypłatę, i ile saldo spadnie poniżej zera; przy zakupie za gotówkę w walucie obcej proponuje zapłatę w złotych z przewalutowaniem.
- Konto przyjmuje tylko instrumenty swojego rodzaju: okno transakcji przy zakupie pokazuje tylko dozwolone instrumenty i odmawia reszty (np. obligacji skarbowych na koncie Regular, złota fizycznego na koncie Obligacje), a import i potwierdzane szkice ostrzegają zamiast odmawiać.
- Aplikacja ma użytkowników: ekran logowania (pseudonim i hasło) przy każdym starcie, osobne dane dla każdego i przełączanie użytkownika w menu awatara; dotychczasowe dane trafiają do pierwszego utworzonego użytkownika.
- Karta instrumentu pokazuje dla funduszy i ETF-ów TER, wielkość funduszu i emitenta według Yahoo (tylko to, co Yahoo podaje), a "Dodaj jako instrument" uzupełnia pusty TER.
- Karta polskiego funduszu, PPK lub ETF-u z GPW pokazuje TFI, grupę i benchmark według analizy.pl (tylko to, co analizy.pl podaje).
- Karta funduszu lub ETF-u pokazuje jego dziesięć największych składników z udziałami (Yahoo, a dla polskich funduszy i PPK analizy.pl wraz z dniem stanu).
- Wykres, ceny i stopy zwrotu na Karcie instrumentu można przełączyć na inną walutę (PLN, EUR, USD); ceny są przeliczane kursami NBP z dnia notowania.
- Awatar z inicjałami i pseudonimem w prawym górnym rogu otwiera menu: Ustawienia, motyw, Pomoc i przełączenie użytkownika; przycisk motywu przeniósł się do tego menu.
- W Ustawieniach jest sekcja Użytkownik: zmiana pseudonimu i hasła oraz usunięcie użytkownika razem z jego folderem i kopiami zapasowymi.
- W nagłówku jest przycisk „Wesprzyj”, który otwiera stronę buycoffee.to w przeglądarce.
- Wyszukiwarka w nagłówku znajduje typ obligacji skarbowych po kodzie (np. EDO) lub okresie (np. „10-letnie”); jego karta pokazuje bieżącą ofertę MF, Twoje serie tego typu i przycisk „Kup”, który otwiera zakup obligacji.

### Poprawki
- Górny pasek z wyszukiwarką ma pełne tło, więc przewijana treść nie nachodzi już na napisy w pasku.
- W motywie Golden pytania w Pomocy mają ciemne tło zamiast białego, więc są czytelne.

## 1.0.1 — 2026-10-20

### Nowe funkcje
- Wyszukiwarka w nagłówku znajduje instrumenty po nazwie, ISIN lub symbolu i otwiera Kartę instrumentu z wykresem notowań.
- Nowy wygląd Dashboardu i motyw Golden, przełączany przyciskiem w nagłówku.
- Sentencja dnia na Dashboardzie i w menu.
- Kliknięcie numeru wersji pod logo pokazuje historię zmian, a po aktualizacji aplikacja raz pokazuje, co nowego.
- Rodzaj instrumentu (ETF, ETC, Fundusz, Kryptowaluta i inne): ustawiany automatycznie przy dodawaniu, z sekcjami i wyszukiwarką w Ustawieniach oraz grupowaniem pozycji w Portfolio.

### Poprawki
- W motywie Golden czytelne są pasma Strategii inwestycyjnej, mapa Kont, wyróżnione pole Konto, teksty zysków, strat i ostrzeżeń oraz podświetlony wiersz.
- Pole Konto w oknach lokaty i reguły cyklicznej ma ten sam kolor co w oknie transakcji.

### Zmiany
- Przycisk „+” dodawania transakcji nie jest pokazywany na Dashboardzie.
- Zakładki z danymi zajmują całą szerokość okna, do 1536 pikseli.

## 1.0.0 — 2026-10-19

Pierwsze wydanie.

### Nowe funkcje
- Transakcje na wielu Kontach (także IKE, IKZE i OKI) oraz Portfolio z pozycjami, partiami i saldem gotówki.
- Automatyczne wyceny z Yahoo, Bossy, Bankiera i analizy.pl, historia notowań ze Stooq oraz kursy walut NBP.
- Obligacje skarbowe: Serie, wycena, przedterminowy wykup, zapadalność i kalendarz odsetek.
- Dashboard, Historia portfela i Wyniki z wykresami, stopą zwrotu i wynikiem realnym.
- Strategie inwestycyjne, Benchmarki, Podsumowanie sprzedaży i kalendarz dochodu pasywnego.
- Import transakcji z XTB i z arkusza oraz Uzgadnianie z wyciągiem.
- Limity wpłat na IKE, IKZE i OKI, lokaty terminowe i Reguły cykliczne.
- Instalator dla Windows z kopią zapasową bazy przy każdym starcie.
