# Historia zmian

## Nieopublikowane

### Nowe funkcje
- Import kryptowalut czyta też eksport CSV z Trezor Suite; jego opłata sieciowa wysyłki jest importowana jak opłata wypłaty z Binance, a przeniesienie bez pary w innych eksportach możesz przypisać do konta, pominąć albo zostawić na później.
- Do importu kryptowalut można wskazać jeden folder z eksportami z Binance, OKX i Trezora naraz (także w podfolderach): każde źródło ma swoje konto, całość zapisuje się jednym „Zastosuj”, wiersz z dwóch kopii pliku liczy się raz, a przeniesienie między giełdą a portfelem, które jest w obu eksportach, zapisuje się tylko raz, niezależnie od kolejności importu.
- Import kryptowalut otwiera okno, które prowadzi krok po kroku: jak pobrać eksporty, wybór folderu, kont i monet, proponowane wpłaty w dniach, w których zakupy zdjęłyby gotówkę konta poniżej zera (do odznaczenia), podgląd i wskazówki do ręcznych poprawek po imporcie; wpłaty są proponowane także dla historii zaimportowanej wcześniej.

## 1.3.1 — 2026-10-29

### Poprawki
- Usunięcie użytkownika nie zawodzi już, gdy w chwili wylogowania działało jeszcze odświeżanie wycen albo historii: plik bazy jest zamykany od razu po zakończeniu tej pracy, więc folder użytkownika znika zamiast zostawać na liście.

## 1.3.0 — 2026-10-29

### Nowe funkcje
- Import z OKX czyta też plik Funding History: zakupy spoza zleceń Spot stają się transakcjami kupna, a wpłaty i wypłaty monet przenoszą papiery między kontem OKX a kontem portfela razem z datami i kosztami zakupu; gotówka w stablecoinach i przelewy wewnętrzne OKX są pomijane.

### Poprawki
- Import z OKX bierze dokładne ilości z pliku Trade Details (do 8 miejsc po przecinku) zamiast zaokrąglonych do 4 miejsc z Historii zleceń, więc sprzedaż nie przekracza już posiadanej ilości; zlecenie bez Trade Details trafia na listę z ostrzeżeniem.
- Usunięcie użytkownika czeka do 10 sekund na zwolnienie plików przez Windows (wcześniej 1,5 s), więc na wolnym albo obciążonym komputerze użytkownik i jego folder znikają, zamiast zostawać na liście po powrocie do ekranu logowania.

### Zmiany
- Opłata sieciowa wypłaty z Binance jest importowana jako sprzedaż tych monet w całości jako prowizja (zamiast trafiać na listę do wpisania ręcznie), więc konto giełdy nie zostaje z monetami, które zapłaciły opłatę.

## 1.2.0 — 2026-10-28

### Nowe funkcje
- W Ustawieniach, w zakładce Import, można wczytać eksport CSV z Binance albo OKX: po wyborze konta i instrumentu aplikacja pokazuje transakcje kupna i sprzedaży kryptowalut i zapisuje je po zatwierdzeniu. Ceny z Binance, który ich nie podaje, są pobierane z Yahoo z dnia transakcji, a USDC z OKX liczone jak USD po kursie NBP. Wypłaty z Binance są przenoszone na wskazane konto portfela razem z datami i kosztami zakupu; opłata sieciowa wypłaty trafia na listę do wpisania ręcznie.

## 1.1.3 — 2026-10-26

### Zmiany
- Wydanie sprawdzające automatyczną aktualizację z wersji 1.1.2; bez zmian w działaniu aplikacji.

## 1.1.2 — 2026-10-26

### Nowe funkcje
- KAPITA sprawdza w tle, czy na GitHubie jest nowsza wersja, i pod numerem wersji pokazuje „Dostępna wersja X”; kliknięcie pozwala zainstalować ją jednym przyciskiem: aplikacja pobiera instalator, zamyka się, aktualizuje i uruchamia ponownie, a dane zostają.

## 1.1.1 — 2026-10-26

### Zmiany
- Po wyeksportowaniu raportu lub pliku KAPITA mówi, gdzie on jest: w oknie aplikacji plik trafia do folderu Pobrane, a okienko pokazuje jego ścieżkę i przycisk „Pokaż w folderze”; w przeglądarce pojawia się potwierdzenie pobrania.

## 1.1.0 — 2026-10-26

### Nowe funkcje
- Wyniki mają przycisk „Raport roczny PDF” z wyborem roku (domyślnie ostatni zakończony): jeden plik A4 ze stroną tytułową oraz sekcjami Wyniki roku, Portfolio na koniec roku, Sprzedaże (FIFO) i Dochód pasywny, z liczbami takimi jak w plikach XLSX, dla wybranego konta lub wszystkich; to zestawienie pomocnicze, nie zeznanie podatkowe.
- Portfolio i Dochód pasywny mają przycisk „Eksportuj XLSX” z wyborem roku: Portfolio pokazuje pozycje i konta na koniec wybranego roku (dla bieżącego roku na dziś), a pozycja bez wyceny z tego dnia ma adnotację „brak wyceny” zamiast zgadniętej wartości; Dochód pasywny wypisuje otrzymane w roku dywidendy i odsetki; oba dotyczą wybranego konta lub wszystkich.
- Podsumowanie sprzedaży i Wyniki mają przycisk „Eksportuj XLSX” z wyborem roku (domyślnie ostatni zakończony): plik ma kwoty jako liczby i prawdziwe daty, dotyczy wybranego konta lub wszystkich i w nazwie ma raport, rok i konto; rok bez danych daje plik z informacją, że nie ma czego raportować.
- Dzwonek w nagłówku przypomina o tym, co czeka: szkice do zatwierdzenia (obligacje, lokaty, transakcje cykliczne), instrumenty bez wyceny po odświeżeniu, obligacje i lokaty zapadające w ciągu 30 dni oraz przekroczone limity wpłat; na dzwonku jest liczba nieprzeczytanych, znika po otwarciu listy i wraca, gdy przypomnienie się zmieni; dzwonek zastąpił liczniki „Do zatwierdzenia” w nagłówku.
- Wyszukiwarka w nagłówku (Ctrl+K) jest też paletą poleceń: wpisanie słowa (np. „portf”, „motyw”, „dyskr”) pokazuje pasujące polecenia, a samo „>” wszystkie: przejście do dowolnej zakładki, dodanie transakcji, przełączenie motywu lub trybu dyskrecji, odświeżenie wycen.
- Usunięcie transakcji nie pyta już o potwierdzenie: transakcja znika od razu, a przez kilka sekund na dole okna jest przycisk „Cofnij”, który przywraca ją na to samo miejsce.
- Przycisk oka w nagłówku włącza tryb dyskrecji: kwoty i wykresy się rozmywają (najechanie myszą je odsłania), a wybór jest zapamiętany.
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
- Ustawienia są podzielone na sekcje (Konta, Klasy aktywów, Instrumenty, Import i inne) z przyciskami u góry; pokazują tylko wybraną sekcję, więc nie trzeba przewijać całej strony.

### Poprawki
- Żółty przycisk dodawania transakcji jest zawsze na wierzchu, więc karty (np. w Dochodzie pasywnym) już go nie zasłaniają.
- Klawisz Esc zamyka okna, które można przeciągać (np. dodawanie transakcji), od najnowszego; otwarta lista rozwijana najpierw zamyka się sama.
- Górny pasek z wyszukiwarką ma pełne tło, więc przewijana treść nie nachodzi już na napisy w pasku.
- W motywie Golden pytania w Pomocy mają ciemne tło zamiast białego, więc są czytelne.

### Zmiany
- „Wyceny” w nagłówku pokazują dzień i miesiąc ostatniego odświeżenia (np. „09.10, 18:05”), żeby nagłówek mieścił się w jednym rzędzie.
- Przycisk „Wesprzyj” w nagłówku pokazuje w węższym oknie (poniżej 1440 px) samą ikonę, żeby nagłówek mieścił się w jednej linii.
- Ustawienia nie pokazują już sekcji „Źródła wycen” z kluczem API Stooq, bo klucz nie jest potrzebny (historia działa na Yahoo); zniknęło też pytanie o klucz z Pomocy.

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
