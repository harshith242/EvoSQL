# Probe set v7 — review

30 hand-written questions over formula_1, card_games, superhero, european_football_2. Each section shows the source question and its gold SQL (for non-controls), the new question, the knowledge it relies on, the new gold SQL, the row count and the first 3 rows.

## p01 · formula_1 · paraphrase

**Source 989:** What was the finish time of the champion of the Canadian Grand Prix in 2008?

```sql
SELECT T1.time FROM results AS T1 INNER JOIN races AS T2 ON T1.raceId = T2.raceId WHERE T2.name = 'Canadian Grand Prix' AND T2.year = 2008 AND T1.time LIKE '_:%:__.___'
```

**Question:** How long did the winner of the 2008 Canadian Grand Prix take to finish?

**Knowledge:** In results.time only the race winner has a full clock time (H:MM:SS.mmm); everyone else has a gap like '+x.xxx', so the winner's time matches LIKE '_:%:__.___'.

```sql
SELECT T1.time FROM results AS T1 INNER JOIN races AS T2 ON T1.raceId = T2.raceId WHERE T2.name = 'Canadian Grand Prix' AND T2.year = 2008 AND T1.time LIKE '_:%:__.___'
```

**Rows:** 1

- `('1:36:24.227',)`

## p02 · formula_1 · paraphrase

**Source 967:** How many Netherlandic drivers are among the 3 youngest drivers?

```sql
SELECT COUNT(*) FROM ( SELECT T1.nationality FROM drivers AS T1 ORDER BY JULIANDAY(T1.dob) DESC LIMIT 3) AS T3 WHERE T3.nationality = 'Dutch'
```

**Question:** Of the three youngest drivers, how many are from the Netherlands?

**Knowledge:** Drivers from the Netherlands are stored as nationality = 'Dutch' (a demonym, not the country name).

```sql
SELECT COUNT(*) FROM ( SELECT T1.nationality FROM drivers AS T1 ORDER BY JULIANDAY(T1.dob) DESC LIMIT 3) AS T3 WHERE T3.nationality = 'Dutch'
```

**Rows:** 1

- `(1,)`

## p03 · formula_1 · same_quirk

**Source 989:** What was the finish time of the champion of the Canadian Grand Prix in 2008?

```sql
SELECT T1.time FROM results AS T1 INNER JOIN races AS T2 ON T1.raceId = T2.raceId WHERE T2.name = 'Canadian Grand Prix' AND T2.year = 2008 AND T1.time LIKE '_:%:__.___'
```

**Question:** What was the champion's finish time in the 2011 Monaco Grand Prix?

**Knowledge:** In results.time only the race winner has a full clock time (H:MM:SS.mmm); everyone else has a gap like '+x.xxx', so the winner's time matches LIKE '_:%:__.___'.

```sql
SELECT T1.time FROM results AS T1 INNER JOIN races AS T2 ON T1.raceId = T2.raceId WHERE T2.name = 'Monaco Grand Prix' AND T2.year = 2011 AND T1.time LIKE '_:%:__.___'
```

**Rows:** 1

- `('2:09:38.373',)`

## p04 · formula_1 · same_quirk

**Source 846:** Please list the reference names of the drivers who are eliminated in the first period in race number 20.

```sql
SELECT d.driverRef FROM qualifying AS q JOIN drivers AS d ON d.driverId = q.driverId WHERE q.raceId = 20 AND q.q2 IS NULL ORDER BY q.q1 DESC;
```

**Question:** Please list the reference names of the drivers who were eliminated in the first period in race number 25.

**Knowledge:** A driver knocked out in the first qualifying period (Q1) has q2 IS NULL in qualifying; 'race number' is raceId.

```sql
SELECT d.driverRef FROM qualifying AS q JOIN drivers AS d ON d.driverId = q.driverId WHERE q.raceId = 25 AND q.q2 IS NULL ORDER BY q.q1 DESC
```

**Rows:** 5

- `('sutil',)`
- `('fisichella',)`
- `('barrichello',)`

## p05 · formula_1 · new_surface

**Source 967:** How many Netherlandic drivers are among the 3 youngest drivers?

```sql
SELECT COUNT(*) FROM ( SELECT T1.nationality FROM drivers AS T1 ORDER BY JULIANDAY(T1.dob) DESC LIMIT 3) AS T3 WHERE T3.nationality = 'Dutch'
```

**Question:** How many drivers are from Holland?

**Knowledge:** Holland / the Netherlands is stored as nationality = 'Dutch' (a demonym, not the country name).

```sql
SELECT COUNT(*) FROM drivers WHERE nationality = 'Dutch'
```

**Rows:** 1

- `(17,)`

## p06 · formula_1 · new_surface

**Source 846:** Please list the reference names of the drivers who are eliminated in the first period in race number 20.

```sql
SELECT d.driverRef FROM qualifying AS q JOIN drivers AS d ON d.driverId = q.driverId WHERE q.raceId = 20 AND q.q2 IS NULL ORDER BY q.q1 DESC;
```

**Question:** Which drivers didn't make it through to Q2 in race No. 30? Give their full names.

**Knowledge:** Not reaching Q2 means q2 IS NULL in qualifying; 'race No.' is raceId; full name is forename, surname.

```sql
SELECT d.forename, d.surname FROM qualifying AS q JOIN drivers AS d ON d.driverId = q.driverId WHERE q.raceId = 30 AND q.q2 IS NULL
```

**Rows:** 5

- `('Rubens', 'Barrichello')`
- `('Jenson', 'Button')`
- `('Adrian', 'Sutil')`

## p07 · formula_1 · control

**Source:** none (control)

**Question:** Which circuit has hosted the most races?

**Knowledge:** none

```sql
SELECT T1.name FROM circuits AS T1 INNER JOIN races AS T2 ON T2.circuitId = T1.circuitId GROUP BY T1.circuitId ORDER BY COUNT(T2.raceId) DESC LIMIT 1
```

**Rows:** 1

- `('Autodromo Nazionale di Monza',)`

## p08 · formula_1 · control

**Source:** none (control)

**Question:** In which year were the most races held?

**Knowledge:** none

```sql
SELECT year FROM races GROUP BY year ORDER BY COUNT(raceId) DESC LIMIT 1
```

**Rows:** 1

- `(2016,)`

## p09 · card_games · paraphrase

**Source 405:** How many Brazilian Portuguese translated sets are inside the Commander block?

```sql
SELECT COUNT(T1.id) FROM sets AS T1 INNER JOIN set_translations AS T2 ON T1.code = T2.setCode WHERE T2.language = 'Portuguese (Brazil)' AND T1.block = 'Commander'
```

**Question:** How many sets in the Commander block have been translated into Brazilian Portuguese?

**Knowledge:** Brazilian Portuguese is stored as language = 'Portuguese (Brazil)'; set-name translations are in set_translations (sets.code = set_translations.setCode).

```sql
SELECT COUNT(T1.id) FROM sets AS T1 INNER JOIN set_translations AS T2 ON T1.code = T2.setCode WHERE T2.language = 'Portuguese (Brazil)' AND T1.block = 'Commander'
```

**Rows:** 1

- `(7,)`

## p10 · card_games · paraphrase

**Source 479:** Among the cards with converted mana cost higher than 5 in the set Coldsnap, how many of them have unknown power?

```sql
SELECT SUM(CASE WHEN T1.power = '*' OR T1.power IS NULL THEN 1 ELSE 0 END) FROM cards AS T1 INNER JOIN sets AS T2 ON T2.code = T1.setCode WHERE T2.name = 'Coldsnap' AND T1.convertedManaCost > 5
```

**Question:** In the Coldsnap set, how many cards costing more than 5 converted mana have an unknown power?

**Knowledge:** Unknown power means power IS NULL or power = '*' (power is stored as text).

```sql
SELECT SUM(CASE WHEN T1.power = '*' OR T1.power IS NULL THEN 1 ELSE 0 END) FROM cards AS T1 INNER JOIN sets AS T2 ON T2.code = T1.setCode WHERE T2.name = 'Coldsnap' AND T1.convertedManaCost > 5
```

**Rows:** 1

- `(6,)`

## p11 · card_games · same_quirk

**Source 468:** What is the Simplified Chinese translation of the name of the set "Eighth Edition"?

```sql
SELECT T2.translation FROM sets AS T1 INNER JOIN set_translations AS T2 ON T2.setCode = T1.code WHERE T1.name = 'Eighth Edition' AND T2.language = 'Chinese Simplified'
```

**Question:** What is the Simplified Chinese translation of the name of the set "Coldsnap"?

**Knowledge:** Simplified Chinese is stored as language = 'Chinese Simplified' (reversed word order); set-name translations are in set_translations.

```sql
SELECT T2.translation FROM sets AS T1 INNER JOIN set_translations AS T2 ON T2.setCode = T1.code WHERE T1.name = 'Coldsnap' AND T2.language = 'Chinese Simplified'
```

**Rows:** 1

- `('骤霜',)`

## p12 · card_games · same_quirk

**Source 416:** What percentage of cards without power are in French?

```sql
SELECT CAST(COUNT(DISTINCT CASE WHEN T2.language = 'French' THEN T1.id ELSE NULL END) AS REAL) * 100 / COUNT(DISTINCT T1.id) FROM cards AS T1 LEFT JOIN foreign_data AS T2 ON T1.uuid = T2.uuid WHERE T1.power IS NULL OR T1.power = '*'
```

**Question:** What percentage of cards without power have a Japanese version?

**Knowledge:** Cards without (unknown) power have power IS NULL or power = '*'; foreign_data has one row per card per language, so count distinct cards over a LEFT JOIN.

```sql
SELECT CAST(COUNT(DISTINCT CASE WHEN T2.language = 'Japanese' THEN T1.id ELSE NULL END) AS REAL) * 100 / COUNT(DISTINCT T1.id) FROM cards AS T1 LEFT JOIN foreign_data AS T2 ON T1.uuid = T2.uuid WHERE T1.power IS NULL OR T1.power = '*'
```

**Rows:** 1

- `(50.764821434321966,)`

## p13 · card_games · new_surface

**Source 352:** Calculate the percentage of the cards availabe in Chinese Simplified.

```sql
SELECT CAST(COUNT(DISTINCT CASE WHEN T2.language = 'Chinese Simplified' THEN T1.id ELSE NULL END) AS REAL) * 100 / COUNT(DISTINCT T1.id) FROM cards AS T1 LEFT JOIN foreign_data AS T2 ON T1.uuid = T2.uuid
```

**Question:** What share of cards have a Traditional Chinese translation? Give it as a percentage.

**Knowledge:** Traditional Chinese is stored as language = 'Chinese Traditional' (reversed word order); foreign_data has one row per card per language, so count distinct cards over a LEFT JOIN.

```sql
SELECT CAST(COUNT(DISTINCT CASE WHEN T2.language = 'Chinese Traditional' THEN T1.id ELSE NULL END) AS REAL) * 100 / COUNT(DISTINCT T1.id) FROM cards AS T1 LEFT JOIN foreign_data AS T2 ON T1.uuid = T2.uuid
```

**Rows:** 1

- `(19.545246559431206,)`

## p14 · card_games · new_surface

**Source 405:** How many Brazilian Portuguese translated sets are inside the Commander block?

```sql
SELECT COUNT(T1.id) FROM sets AS T1 INNER JOIN set_translations AS T2 ON T1.code = T2.setCode WHERE T2.language = 'Portuguese (Brazil)' AND T1.block = 'Commander'
```

**Question:** How many sets in the Kamigawa block have a Portuguese translation?

**Knowledge:** The only Portuguese variant stored is language = 'Portuguese (Brazil)'; set-name translations are in set_translations.

```sql
SELECT COUNT(T1.id) FROM sets AS T1 INNER JOIN set_translations AS T2 ON T1.code = T2.setCode WHERE T2.language = 'Portuguese (Brazil)' AND T1.block = 'Kamigawa'
```

**Rows:** 1

- `(3,)`

## p15 · card_games · control

**Source:** none (control)

**Question:** In which year were the most rulings issued?

**Knowledge:** none

```sql
SELECT STRFTIME('%Y', date) FROM rulings GROUP BY STRFTIME('%Y', date) ORDER BY COUNT(id) DESC LIMIT 1
```

**Rows:** 1

- `('2017',)`

## p16 · card_games · control

**Source:** none (control)

**Question:** How many sets were released in 2010?

**Knowledge:** none

```sql
SELECT COUNT(id) FROM sets WHERE STRFTIME('%Y', releaseDate) = '2010'
```

**Rows:** 1

- `(23,)`

## p17 · superhero · paraphrase

**Source 747:** What is the total number of superheroes without full name?

```sql
SELECT COUNT(id) FROM superhero WHERE full_name IS NULL OR full_name = '-'
```

**Question:** How many heroes don't have a full name on record?

**Knowledge:** A missing full name is stored either as NULL or as the placeholder '-'.

```sql
SELECT COUNT(id) FROM superhero WHERE full_name IS NULL OR full_name = '-'
```

**Rows:** 1

- `(247,)`

## p18 · superhero · paraphrase

**Source 750:** What is the average weight of all female superheroes?

```sql
SELECT AVG(weight_kg) FROM superhero s JOIN gender g ON s.gender_id = g.id WHERE g.gender = 'Female' AND weight_kg > 0;
```

**Question:** On average, how much do female superheroes weigh?

**Knowledge:** weight_kg = 0 (or NULL) means the weight is missing, so averages use weight_kg > 0.

```sql
SELECT AVG(weight_kg) FROM superhero s JOIN gender g ON s.gender_id = g.id WHERE g.gender = 'Female' AND weight_kg > 0
```

**Rows:** 1

- `(78.50694444444444,)`

## p19 · superhero · same_quirk

**Source 791:** Calculate the average height for all superhero.

```sql
SELECT AVG(height_cm) FROM superhero WHERE height_cm > 0;
```

**Question:** What's the average height of DC Comics heroes?

**Knowledge:** height_cm = 0 (or NULL) means the height is missing, so averages use height_cm > 0.

```sql
SELECT AVG(T1.height_cm) FROM superhero AS T1 INNER JOIN publisher AS T2 ON T1.publisher_id = T2.id WHERE T2.publisher_name = 'DC Comics' AND T1.height_cm > 0
```

**Rows:** 1

- `(220.3987341772152,)`

## p20 · superhero · same_quirk

**Source 822:** How many green-skinned villains are there in the superhero universe?

```sql
SELECT COUNT(T1.id) FROM superhero AS T1 INNER JOIN alignment AS T2 ON T1.alignment_id = T2.id INNER JOIN colour AS T3 ON T1.skin_colour_id = T3.id WHERE T2.alignment = 'Bad' AND T3.colour = 'Green'
```

**Question:** How many female villains are there?

**Knowledge:** Villains are alignment = 'Bad'.

```sql
SELECT COUNT(T1.id) FROM superhero AS T1 INNER JOIN alignment AS T2 ON T1.alignment_id = T2.id INNER JOIN gender AS T3 ON T1.gender_id = T3.id WHERE T2.alignment = 'Bad' AND T3.gender = 'Female'
```

**Rows:** 1

- `(35,)`

## p21 · superhero · new_surface

**Source 747:** What is the total number of superheroes without full name?

```sql
SELECT COUNT(id) FROM superhero WHERE full_name IS NULL OR full_name = '-'
```

**Question:** Which Dark Horse Comics heroes have an unknown real name?

**Knowledge:** A hero's real name is full_name; an unknown one is stored as NULL or the placeholder '-'.

```sql
SELECT T1.superhero_name FROM superhero AS T1 INNER JOIN publisher AS T2 ON T1.publisher_id = T2.id WHERE T2.publisher_name = 'Dark Horse Comics' AND (T1.full_name IS NULL OR T1.full_name = '-')
```

**Rows:** 3

- `('Captain Midnight',)`
- `('Jason Voorhees',)`
- `('Johann Krauss',)`

## p22 · superhero · new_surface

**Source 750:** What is the average weight of all female superheroes?

```sql
SELECT AVG(weight_kg) FROM superhero s JOIN gender g ON s.gender_id = g.id WHERE g.gender = 'Female' AND weight_kg > 0;
```

**Question:** How many Marvel Comics heroes have no weight listed?

**Knowledge:** A missing weight is stored as weight_kg = 0 or NULL.

```sql
SELECT COUNT(T1.id) FROM superhero AS T1 INNER JOIN publisher AS T2 ON T1.publisher_id = T2.id WHERE T2.publisher_name = 'Marvel Comics' AND (T1.weight_kg = 0 OR T1.weight_kg IS NULL)
```

**Rows:** 1

- `(66,)`

## p23 · superhero · control

**Source:** none (control)

**Question:** What's the average intelligence score across all heroes?

**Knowledge:** none

```sql
SELECT AVG(T1.attribute_value) FROM hero_attribute AS T1 INNER JOIN attribute AS T2 ON T1.attribute_id = T2.id WHERE T2.attribute_name = 'Intelligence'
```

**Rows:** 1

- `(84.3338683788122,)`

## p24 · european_football_2 · paraphrase

**Source 1025:** Give the name of the league had the most goals in the 2016 season?

```sql
SELECT t2.name FROM Match AS t1 INNER JOIN League AS t2 ON t1.league_id = t2.id WHERE t1.season = '2015/2016' GROUP BY t2.name ORDER BY SUM(t1.home_team_goal + t1.away_team_goal) DESC LIMIT 1
```

**Question:** In the 2016 season, which league had the highest total number of goals?

**Knowledge:** Seasons are stored as 'YYYY/YYYY' text; 'the 2016 season' is season = '2015/2016'.

```sql
SELECT t2.name FROM Match AS t1 INNER JOIN League AS t2 ON t1.league_id = t2.id WHERE t1.season = '2015/2016' GROUP BY t2.name ORDER BY SUM(t1.home_team_goal + t1.away_team_goal) DESC LIMIT 1
```

**Rows:** 1

- `('Spain LIGA BBVA',)`

## p25 · european_football_2 · paraphrase

**Source 1091:** How many matches were held in the Belgium Jupiler League in April, 2009?

```sql
SELECT COUNT(t2.id) FROM League AS t1 INNER JOIN Match AS t2 ON t1.id = t2.league_id WHERE t1.name = 'Belgium Jupiler League' AND SUBSTR(t2."date", 1, 7) = '2009-04'
```

**Question:** How many games were played in the Belgian Jupiler League in April 2009?

**Knowledge:** The league is stored as 'Belgium Jupiler League'; Match.date is text 'YYYY-MM-DD 00:00:00', so a month is SUBSTR(date, 1, 7).

```sql
SELECT COUNT(t2.id) FROM League AS t1 INNER JOIN Match AS t2 ON t1.id = t2.league_id WHERE t1.name = 'Belgium Jupiler League' AND SUBSTR(t2."date", 1, 7) = '2009-04'
```

**Rows:** 1

- `(36,)`

## p26 · european_football_2 · same_quirk

**Source 1030:** Give the name of the league had the most matches end as draw in the 2016 season?

```sql
SELECT t2.name FROM Match AS t1 INNER JOIN League AS t2 ON t1.league_id = t2.id WHERE t1.season = '2015/2016' AND t1.home_team_goal = t1.away_team_goal GROUP BY t2.name ORDER BY COUNT(t1.id) DESC LIMIT 1
```

**Question:** Which league had the fewest drawn matches in the 2012 season?

**Knowledge:** Seasons are stored as 'YYYY/YYYY' text; 'the 2012 season' is season = '2011/2012'.

```sql
SELECT t2.name FROM Match AS t1 INNER JOIN League AS t2 ON t1.league_id = t2.id WHERE t1.season = '2011/2012' AND t1.home_team_goal = t1.away_team_goal GROUP BY t2.name ORDER BY COUNT(t1.id) ASC LIMIT 1
```

**Rows:** 1

- `('Switzerland Super League',)`

## p27 · european_football_2 · same_quirk

**Source 1113:** For the team "Hannover 96", what was its defence aggression class on 2015/9/10?

```sql
SELECT t2.defenceAggressionClass FROM Team AS t1 INNER JOIN Team_Attributes AS t2 ON t1.team_api_id = t2.team_api_id WHERE t1.team_long_name = 'Hannover 96' AND t2."date" LIKE '2015-09-10%'
```

**Question:** What was Celtic's build up play speed class on 2014/9/19?

**Knowledge:** Team_Attributes.date is text with a time suffix ('YYYY-MM-DD 00:00:00'), so a day is matched with LIKE 'YYYY-MM-DD%'.

```sql
SELECT t2.buildUpPlaySpeedClass FROM Team AS t1 INNER JOIN Team_Attributes AS t2 ON t1.team_api_id = t2.team_api_id WHERE t1.team_long_name = 'Celtic' AND t2."date" LIKE '2014-09-19%'
```

**Rows:** 1

- `('Fast',)`

## p28 · european_football_2 · new_surface

**Source 1025:** Give the name of the league had the most goals in the 2016 season?

```sql
SELECT t2.name FROM Match AS t1 INNER JOIN League AS t2 ON t1.league_id = t2.id WHERE t1.season = '2015/2016' GROUP BY t2.name ORDER BY SUM(t1.home_team_goal + t1.away_team_goal) DESC LIMIT 1
```

**Question:** Which league had the most goals in the season that ended in 2014?

**Knowledge:** Seasons are stored as 'YYYY/YYYY' text named by both years; the season ending in 2014 is season = '2013/2014'.

```sql
SELECT t2.name FROM Match AS t1 INNER JOIN League AS t2 ON t1.league_id = t2.id WHERE t1.season = '2013/2014' GROUP BY t2.name ORDER BY SUM(t1.home_team_goal + t1.away_team_goal) DESC LIMIT 1
```

**Rows:** 1

- `('England Premier League',)`

## p29 · european_football_2 · new_surface

**Source 1091:** How many matches were held in the Belgium Jupiler League in April, 2009?

```sql
SELECT COUNT(t2.id) FROM League AS t1 INNER JOIN Match AS t2 ON t1.id = t2.league_id WHERE t1.name = 'Belgium Jupiler League' AND SUBSTR(t2."date", 1, 7) = '2009-04'
```

**Question:** How many La Liga matches were played in March 2012?

**Knowledge:** La Liga is stored as League.name = 'Spain LIGA BBVA'; Match.date is text 'YYYY-MM-DD 00:00:00', so a month is SUBSTR(date, 1, 7).

```sql
SELECT COUNT(t2.id) FROM League AS t1 INNER JOIN Match AS t2 ON t1.id = t2.league_id WHERE t1.name = 'Spain LIGA BBVA' AND SUBSTR(t2."date", 1, 7) = '2012-03'
```

**Rows:** 1

- `(55,)`

## p30 · european_football_2 · control

**Source:** none (control)

**Question:** Which team has the highest defence pressure score in any of its attribute records? Give the team's long name.

**Knowledge:** none

```sql
SELECT t1.team_long_name FROM Team AS t1 INNER JOIN Team_Attributes AS t2 ON t1.team_api_id = t2.team_api_id ORDER BY t2.defencePressure DESC LIMIT 1
```

**Rows:** 1

- `('FC Bayern Munich',)`
