# EvoSQL v7 results

Online per-database fact memory vs no memory on Arcwise-Plat (corrected BIRD Mini-Dev), with the correct SQL revealed after each answer. Facts are selected by JEV, consolidated during the stream and may carry verified SQL snippets. Each complete (order, database) stream is one unit of evidence.

## Primary: second half of each stream (facts vs none)

| Order | Database | Questions (2nd half) | None | Facts | Diff | Fixes / regressions | Injection rate |
|---|---|---|---|---|---|---|---|
| 0 | formula_1 | 33 | 0.515 | 0.576 | +0.061 | +2 / -0 | 36% |
| 0 | superhero | 26 | 0.885 | 0.846 | -0.038 | +0 / -1 | 19% |
| 0 | card_games | 26 | 0.654 | 0.615 | -0.038 | +0 / -1 | 46% |
| 0 | european_football_2 | 26 | 0.692 | 0.692 | +0.000 | +1 / -1 | 27% |

- **Direction count:** 1 of 4 streams positive, 2 negative, 1 tied.
- **Pooled second-half difference:** +0.000 (95% CI -0.038 to +0.040, resampling databases with both orders together).
- **Leave one database out:** without formula_1 -0.026, without superhero +0.012, without card_games +0.012, without european_football_2 +0.000.
- **Heuristic, not exact (ignores dependence within a stream):** question-level sign-flip p = 1.000; question-clustered 95% CI -0.045 to +0.045.
- **Injection check:** 0 of 4 streams inert (facts injected on fewer than 10% of second-half questions). Where the arm is inert, a null result means the memory was rarely used, not that memory cannot help.

## Whole stream, learning curve and memory size

| Order | Database | None (all) | Facts (all) | Quarters none / facts | Active facts at each quarter |
|---|---|---|---|---|---|
| 0 | formula_1 | 0.591 | 0.621 | 0.75/0.75 · 0.59/0.59 · 0.44/0.44 · 0.59/0.71 | 4 · 9 · 16 · 21 |
| 0 | superhero | 0.808 | 0.788 | 0.85/0.85 · 0.62/0.62 · 0.77/0.69 · 1.00/1.00 | 0 · 4 · 6 · 6 |
| 0 | card_games | 0.615 | 0.615 | 0.38/0.46 · 0.77/0.77 · 0.62/0.62 · 0.69/0.62 | 4 · 7 · 12 · 15 |
| 0 | european_football_2 | 0.725 | 0.725 | 0.83/0.83 · 0.69/0.69 · 0.54/0.54 · 0.85/0.85 | 2 · 5 · 10 · 8 |

## JEV selection

- Questions with at least one injected fact: 50 of 221; mean facts injected per question 0.23.
- Fact scores at or above the cutoff 2.75: 59 of 1538.
- JEV cost in the stream: $0.0218.

## Consolidation

- Passes: 17 run, 0 skipped for budget.
- Edits proposed {'generalize': 8, 'condition': 4, 'merge': 9}, applied {'generalize': 8, 'condition': 4, 'merge': 7}, rejected {'merge': 2}.
- Rejection reasons: {"leakage: contains answer value 'hamilton'": 1, 'probe failed: interrupted': 1}.
- Applied (order 0, formula_1): generalize f1 -> f1: Date-text storage applies to all date columns, not only drivers.dob, so broaden it to help race-date questions too.
- Applied (order 0, formula_1): condition f7, f8, f9 -> f10: Same status column: 'all laps completed' means exactly 'Finished', while 'race completion / finished the race' also includes lapped finishers; rewrite as one conditional fact.
- Applied (order 0, formula_1): merge f11, f16 -> f20: Both facts say the same thing: lap duration is the integer lapTimes.milliseconds, while lapTimes.time is only its display form.
- Applied (order 0, formula_1): condition f10, f15 -> f21: They conflict on whether lapped drivers count as finishing; each question's wording selects its own rule.
- Applied (order 0, formula_1): generalize f4 -> f4: Coordinates rule is not tied to the phrase 'location coordinates'.
- Applied (order 0, formula_1): generalize f22 -> f22: The stored-format rule holds for all qualifying time columns, not only the 0:01:54 example.
- Applied (order 0, formula_1): merge f18, f27 -> f29: Both facts state that a driver's full name is split across drivers.forename and drivers.surname; one covers matching, the other returning.
- Applied (order 0, formula_1): merge f12, f28 -> f30: Both describe results.fastestLapTime as the single-per-race overall fastest-lap marker, not a per-driver best.
- Applied (order 0, formula_1): condition f13, f26 -> f31: Both map results.position phrases; combine to state when =1 versus <>1 applies.
- Applied (order 0, superhero): generalize f3 -> f3: Wording is tied to one stored value instead of the general colour-matching rule, and the stored value itself is missing from values.
- ... and 9 more applied edits.

## Snippets

- Snippets by outcome: {'kept': 21, 'snippet failed: misuse of aggregate: MAX()': 1, 'snippet failed: misuse of aggregate: AVG()': 1, "leakage: question literal 'Marvel Comics'": 1}.
- Facts with SQL in the final facts files: 27 of 70.
- Injections of a fact with SQL: 14 of 51.

## Probe (frozen memory, level by arm: correct / questions, +fixes / -regressions vs none)

| Level | none | v6_facts | v7_prose | v7_sql | examples |
|---|---|---|---|---|---|
| paraphrase | 6/8 | 7/8 (+1 / -0) | 7/8 (+1 / -0) | 7/8 (+1 / -0) | 8/8 (+2 / -0) |
| same_quirk | 6/8 | 7/8 (+1 / -0) | 7/8 (+1 / -0) | 8/8 (+2 / -0) | 8/8 (+2 / -0) |
| new_surface | 5/8 | 6/8 (+1 / -0) | 8/8 (+3 / -0) | 8/8 (+3 / -0) | 8/8 (+3 / -0) |
| control | 5/6 | 5/6 (+0 / -0) | 5/6 (+0 / -0) | 5/6 (+0 / -0) | 6/6 (+1 / -0) |
| all | 22/30 | 25/30 (+3 / -0) | 27/30 (+5 / -0) | 28/30 (+6 / -0) | 30/30 (+8 / -0) |

A controlled check with 6-8 questions per level: raw counts, no p-values.

## Cost, latency, turns

- Logical cost (peak prices; a prompt answered once per run is counted once): none $0.217, facts $0.046, proposer $0.214, pre-check $0.017, consolidation proposer $0.112, consolidation pre-check $0.038, JEV $0.023.
- $ per correct answer: none $0.0014, facts (learning included) $0.0030. Real API spend: $0.522 of $2.00.
- Latency (original API time per answer) p50 / p95 s: none 3.1 / 5.9, facts 3.0 / 5.3.
- Agent turns: none 2.9, facts 2.8.

## Learning

- Learning events: 70; outcomes: {'pre-check unmatched': 44, 'pre-check passed': 15, 'dropped: value not in data': 1, 'dropped: already in docs': 2, 'dropped: no reusable fact proposed': 2, 'dropped: unknown column': 1, 'dropped: leakage': 5}.

### Order 0, formula_1: 31 facts, retired {'consolidated into f10': 3, 'consolidated into f21': 2, 'consolidated into f20': 2, 'consolidated into f30': 2, 'consolidated into f31': 2, 'consolidated into f29': 2}

```
f1 score +0 uses 1 [encoding] drivers.dob: Date columns such as drivers.dob and races.date are stored as text 'YYYY-MM-DD', so birth or race years are the leading four characters rather than whole-date literals.  (applies to: born before, driver date of birth, dob, birth year, race year)
f2 score +0 uses 3 [meaning] drivers.dob: A driver's age is whole calendar years between drivers.dob and today, minus one if this year's birthday has not yet occurred; it is not a fractional day-based count.  (applies to: how old, age, youngest driver, oldest driver)
f3 score +0 uses 0 [mapping] driverStandings.wins: A driver's win count is recorded in driverStandings.wins, carried forward in the standings; 'most wins' questions come from that column, not from counting first-place race results.  (applies to: most wins, winning driver, number of wins, driver with the most wins)
f4 score +0 uses 3 [mapping] circuits.lat: A circuit's coordinates are circuits.lat and circuits.lng; circuits.location, circuits.name and circuits.country describe the place but are never coordinates.  (applies to: location coordinates, circuit coordinates, lat and lng, circuit location, where is the race held)
f5 score +0 uses 0 [mapping] driverStandings.position: 'Track number' or track position for a driver in a race means driverStandings.position, the driver's championship standing at that race, not results.grid (the starting grid slot).  (applies to: track number, in track number less than, track position, standing position)
f6 score +0 uses 0 [mapping] pitStops.duration: 'Average pit stop duration' (shortest/longest pit stops) is taken from pitStops.duration, the per-stop text value in seconds, not from pitStops.milliseconds.  (applies to: average pit stop duration, shortest pit stop, fastest pit stops, German drivers, born between 1980-1985)
f7 score +0 uses 1 RETIRED (consolidated into f10) [mapping] status.status: 'Finished' in status marks that every lap of the race was completed; drivers classified a lap or more down carry separate status values, so all-laps completion matches the exact value 'Finished'.  (applies to: race completion percentage, completed all laps, finished the race, race result status)
f8 score +0 uses 0 RETIRED (consolidated into f10) [relation] results.statusId: A result's completion classification lives in the status table reached through results.statusId; a driver who finished every lap has status 'Finished', so comparing results.laps within the race does not identify them.  (applies to: finished all laps, completed every lap of the race, finished the race, classified finishers, race result status)
f9 score +0 uses 0 RETIRED (consolidated into f10) [mapping] status.status: Drivers who completed the race but were lapped still count as finishers; their status reads like '+1 Lap' or '+2 Laps', so race completion means status 'Finished' plus any '+...Lap...' status.  (applies to: race completion rate, completed the race, finished the race, did not finish, drivers who took part in the race)
f10 score +0 uses 2 RETIRED (consolidated into f21) [mapping] status.status: Questions about finishing all laps or every lap match status 'Finished' exactly; questions about race completion or finishing the race also count lapped finishers, whose status reads '+1 Lap' or '+2 Laps'.  (applies to: all laps completed, finished all laps, race completion rate, completed the race, finished the race)
f11 score +0 uses 0 RETIRED (consolidated into f20) [mapping] lapTimes.milliseconds: 'Fastest/best lap time' questions report and rank on lapTimes.milliseconds, the integer lap duration; lapTimes.time is only the formatted 'M:SS.mmm' display of the same lap, not the answer value.  (applies to: fastest lap time recorded, lap time)
f12 score +0 uses 0 RETIRED (consolidated into f30) [mapping] results.fastestLapTime: A driver's own fastest lap is stored per lap in lapTimes (one row per driver per lap); results.fastestLapTime only marks the single overall fastest lap of each race, so it misses most driver bests.  (applies to: Michael Schumacher, driver's fastest lap)
f13 score +0 uses 0 RETIRED (consolidated into f31) [mapping] results.position: The champion or winner of a race is the driver with results.position = 1, the official finishing place; results.positionOrder is a separate classification column, not the winner marker.  (applies to: champion of each race, winner of a race, won the race)
f14 score +0 uses 1 [encoding] results.fastestLapSpeed: Fastest lap speed is stored in results.fastestLapSpeed as a text string such as '222.592'; report and rank the stored text value itself, since the answer is expected in that stored form, not as a numeric conversion.  (applies to: fastest lap speed, highest lap speed, lap speed in the 2009 Spanish Grand Prix, fastest speed of a driver, speed ranking in a race)
f15 score +0 uses 0 RETIRED (consolidated into f21) [mapping] results.time: A 'finisher' is a result row whose results.time is not null (a recorded finish time); rows lacking a time did not finish and must be excluded from finisher counts, whatever their status.  (applies to: finishers, how many finishers, drivers who finished, disqualified finishers)
f16 score +0 uses 0 RETIRED (consolidated into f20) [mapping] lapTimes.milliseconds: A driver's 'average lap time' is reported as the plain numeric average of lapTimes.milliseconds, not converted into an 'M:SS.mmm' text display.  (applies to: average lap time, mean lap time, average time per lap, Hamilton lap time)
f17 score +0 uses 0 [mapping] results.time: In results, a race champion (winner) is the row whose results.time is the leader's total, written with two colons (H:MM:SS.mmm); every other finisher's time starts with '+' as a gap.  (applies to: fastest lap number of the champion, winner of each race in 2009)
f18 score +2 uses 4 RETIRED (consolidated into f29) [mapping] drivers.forename: A driver's full name is split across drivers.forename and drivers.surname, so a question naming a driver must match both parts separately; no single full-name column exists.  (applies to: Lewis Hamilton, driver named in a question, full name, forename and surname)
f19 score +0 uses 0 [relation] driverStandings.raceId: Every race a driver entered, including their first race, is recorded in driverStandings, one row per driver per race; results covers fewer driver-race pairs, so first-race questions must join races through driverStandings.  (applies to: first race joined, driver debut, first race, youngest racer, race entered)
f20 score +0 uses 0 [mapping] lapTimes.milliseconds: Fastest and average lap times are reported and ranked on the integer lapTimes.milliseconds; lapTimes.time is only the formatted 'M:SS.mmm' display of the same lap, never the answer value.  (applies to: fastest lap time recorded, best lap time, average lap time, mean lap time, lap time)
f21 score +0 uses 2 [mapping] finishing a race: For finishing questions: 'all laps completed' or 'every lap' matches status 'Finished' plus lapped statuses starting '+'; a plain 'finishers' count instead keeps rows where results.time is not null.  (applies to: all laps completed, every lap, finishers, race completion, completed the race)
f22 score +0 uses 1 [encoding] qualifying.q3: Qualifying times qualifying.q1/q2/q3 are stored as 'M:SS.mmm' with an unpadded minute and no hour part, so a question time written H:MM:SS matches the stored minute:second prefix.  (applies to: Q3 time, qualifying lap time, Q1/Q2/Q3 times, finished 0:01:54, qualifying race No.903)
f23 score +0 uses 0 [mapping] results.fastestLapTime: 'Lap record' means the smallest lap time: compare results.fastestLapTime after converting its 'M:SS.mmm' text to seconds; ranking by fastestLapSpeed fails because circuits differ in length.  (applies to: lap record, circuits in Italy)
f24 score +0 uses 0 [mapping] constructorResults.points: A constructor's points in a race are stored in constructorResults, one row per constructor per race; results.points are per-driver points and are not the team's score.  (applies to: constructor scored most points, team points in a race, constructor points, which team scored most)
f25 score +0 uses 0 [mapping] seasons.url: A season's 'page' means its link stored in seasons.url, reached by matching races.year to seasons.year; the season year number is not the page.  (applies to: season page, season link, year page, season of a race)
f26 score +0 uses 0 RETIRED (consolidated into f31) [mapping] results.position: 'Did not finish' in these questions means not finishing first: it is counted from results.position not equal to 1, not from status text; rows with a null position are excluded.  (applies to: did not finish, not first, 1st, percentage not first)
f27 score +2 uses 1 RETIRED (consolidated into f29) [mapping] drivers.forename: A driver's full name in answers is the two separate columns drivers.forename and drivers.surname; questions asking for 'full names' expect both columns returned, not a concatenated single value.  (applies to: full name, full names of drivers, list the full names, driver name)
f28 score +0 uses 0 RETIRED (consolidated into f30) [mapping] results.fastestLapTime: Having the fastest lap time in a race means results.fastestLapTime is filled in (one such row per race); results.rank is not the marker for that driver.  (applies to: has the fastest lap, drivers with the fastest lap)
f29 score +2 uses 4 [mapping] drivers.forename: A driver's full name is the two columns drivers.forename and drivers.surname; a named driver is matched on both parts separately, and 'full name' questions return both columns, never a concatenation.  (applies to: full name, full names of drivers, driver named in a question, forename and surname, driver name)
f30 score +0 uses 0 [mapping] results.fastestLapTime: results.fastestLapTime is filled for the one overall fastest lap of each race, not a driver's own best; per-driver fastest laps come from lapTimes, and results.rank is not that marker.  (applies to: has the fastest lap, drivers with the fastest lap, driver's fastest lap, fastest lap time, fastest lap in a race)
f31 score +0 uses 0 [mapping] results.position: 'Winner'/'champion' of a race means results.position = 1 (results.positionOrder is a separate classification); a question of a driver not finishing first counts results.position <> 1, with null positions excluded.  (applies to: champion of each race, winner of a race, won the race, did not finish, not first)
```

### Order 0, superhero: 7 facts, retired {'regression while unproven': 1}

```
f1 score +0 uses 0 [relation] superhero.publisher_id: superhero.publisher_id, race_id and alignment_id are null for a few heroes, so joining superhero to those lookup tables drops them from per-group counts and averages.  (applies to: published by Marvel Comics, publisher of superheroes, number of superheroes published, race of superheroes, alignment of superheroes)
f2 score +0 uses 4 [mapping] publisher.publisher_name: Publisher names in questions match publisher.publisher_name exactly as stored, so a shortened name such as 'DC' or 'Marvel' means 'DC Comics' or 'Marvel Comics'.  (applies to: DC, Marvel, DC Comics, Marvel Comics, publisher name)
f3 score +0 uses 0 [mapping] colour.colour: Eye, hair and skin colours are compared by their stored colour value; 'No Colour' is a stored value meaning the hero has none and still counts as a match.  (applies to: same eyes, hair and skin colour, matching colour, eye colour, hair colour, skin colour)
f4 score +0 uses 0 [encoding] superhero.full_name: When a superhero's full name is unknown or missing it is stored as '-', never as an empty string.  (applies to: without full name, missing full name, no full name, unknown full name, null full_name)
f5 score +0 uses 0 [grain] superhero.superhero_name: One superhero row is one hero, but superhero_name is not unique, so filtering by a hero's name can match several heroes and repeat a publisher.  (applies to: publisher for a named hero, hero name, named superheroes, Hawkman)
f6 score -1 uses 1 RETIRED (regression while unproven) [grain] hero_attribute.attribute_value: Attribute scores repeat across heroes: many heroes tie at the same attribute_value for one attribute, so a superlative like dumbest or smartest matches every hero at the lowest or highest score, not just one.  (applies to: dumbest superhero, lowest intelligence, smartest superhero, highest attribute value, weakest hero)
f7 score +0 uses 1 [grain] hero_attribute.attribute_value: The top value of an attribute (e.g. the highest Speed) is usually shared by several heroes, so a question asking for the 'fastest' or 'best' hero can match multiple heroes.  (applies to: fastest, strongest, most intelligent, highest attribute value, hero with the highest Speed)
```

### Order 0, card_games: 21 facts, retired {'consolidated into f19': 2, 'consolidated into f14': 2, 'consolidated into f21': 2, 'consolidated into f20': 2, 'regression while unproven': 1}

```
f1 score +1 uses 6 [mapping] proportion: A proportion or percentage of cards is the exact fraction times 100 on a 0-100 scale, given unrounded, not rounded to a fixed number of decimals.  (applies to: proportion of cards, percentage of cards, what proportion, percentage)
f2 score +0 uses 2 RETIRED (consolidated into f19) [mapping] cards.power: A card's power counts as unknown only when cards.power is exactly '*' or NULL; values such as '1+*' are real, known powers, not unknown.  (applies to: unknown power, power is unknown, cards with unknown power, power value)
f3 score +0 uses 1 [mapping] cards.cardKingdomFoilId: "Powerful foils" means cards.cardKingdomFoilId and cards.cardKingdomId are both non-null together; a card without powerful foils has either of those two columns NULL.  (applies to: powerful foils, without powerful foils, borderless card ids, available without powerful foils)
f4 score +0 uses 2 RETIRED (consolidated into f14) [relation] set_translations.language: A set's language version (e.g. Korean) is recorded in set_translations, matched to the set via set_translations.setCode equals the card's setCode; foreign_data holds only per-card foreign text, never set language.  (applies to: Korean version, sets with a Korean version, foreign language version of a set, set translations, translated set name)
f5 score +0 uses 0 [relation] foreign_data.uuid: cards.uuid matches foreign_data.uuid, one foreign_data row per card per language; a card's supertypes and subtypes stay on cards, while foreign_data.type holds only the translated type text.  (applies to: types of cards in German, German card types, supertypes, subtypes, card types)
f6 score +0 uses 4 RETIRED (consolidated into f21) [relation] legalities.uuid: legalities matches cards on uuid with one row per format, so banned status is per-format; some cards have no legalities row, so joining drops them.  (applies to: banned, is banned, legality, frame styles, Allen Williams)
f7 score +0 uses 0 [meaning] foreign_data.flavorText: foreign_data.flavorText holds a card's flavor text for that row's language independently of cards.flavorText, so a card can have foreign flavor text while its cards.flavorText is null.  (applies to: Italian flavor text, flavor text in another language, foreign flavor text, translated flavor text)
f8 score +0 uses 2 [relation] rulings.text: Info a card contains about rules like triggered abilities lives in rulings.text, joined to cards via rulings.uuid = cards.uuid; cards.text holds only the printed rules text, and one card may have many rulings rows.  (applies to: contains info about the triggered ability, triggered ability, card rulings, info about the ability)
f9 score +0 uses 0 RETIRED (consolidated into f20) [mapping] cards.types: A card's type named in a question (e.g. Creature) matches cards.types exactly as one comma-separated element; cards.type concatenates supertypes and subtypes, so substring matching there is wrong.  (applies to: type Creature, creature cards, type of the card)
f10 score +0 uses 0 [relation] sets.name: A set named in a question matches sets.name, not cards.setCode: card rows store only the set abbreviation (sets.code, e.g. 'CSP'), so the set must be joined via sets.code = cards.setCode to filter by name.  (applies to: cards in the set Coldsnap, set name, set Coldsnap, in a given set)
f11 score +0 uses 0 RETIRED (consolidated into f21) [grain] legalities.format: One legalities row is one card's status in one format, so the number of banned cards per play format comes from grouping legalities rows by format and counting those with status 'Banned'; no format is fixed in advance.  (applies to: play format, banned status, format with the most banned cards, number of banned status)
f12 score +0 uses 0 [grain] rulings.uuid: Counting a card's rulings groups rulings rows by uuid; several cards can share the same maximum number of rulings, so the top count is not unique to one card.  (applies to: card with the most rulings, most ruling information, maximum number of rulings)
f13 score +0 uses 1 RETIRED (consolidated into f14) [mapping] set_translations.translation: A set counts as having a translation only when set_translations.translation is non-null; an existing foreign-language row whose translation is NULL does not mean the set is translated.  (applies to: Italian translation, has a translation, translated set, sets in a block)
f14 score -1 uses 3 RETIRED (regression while unproven) [mapping] set_translations: A set's named-language version matches set_translations.language joined on setCode; 'translated' additionally requires set_translations.translation non-null, since a language row can exist with a NULL translation.  (applies to: Korean version, Italian translation, has a translation, translated set, sets with a language version)
f15 score +0 uses 0 [grain] cards.name: One cards row is a single printing, so a card name like 'Serra Angel' matches many rows that may share or differ in converted mana cost; a name is not a unique key.  (applies to: which card costs more converted mana, card name, Serra Angel, Shrine Keeper, costs more)
f16 score +0 uses 0 [encoding] cards.name: Card names in cards.name are stored verbatim, so an apostrophe within a name is part of the stored value and the whole name must be matched as one exact text string.  (applies to: card name, name with apostrophe, Italian name of the set, set of cards)
f17 score +0 uses 0 RETIRED (consolidated into f20) [mapping] cards.originalType: A card type named in a question (e.g. Artifact) is a whole value in cards.originalType; cards.types instead holds comma-separated types and cards.type the full printed type line.  (applies to: Artifact cards, type of card, which are black, foreign language translation)
f18 score +0 uses 0 RETIRED (consolidated into f19) [mapping] cards.power: A card described in a question as having no power or being without power covers two stored states: cards.power NULL and the literal '*', so filtering on only one state undercounts such cards.  (applies to: without power, no power, cards without power, unknown power, powerless)
f19 score +0 uses 2 [mapping] cards.power: A card's power is unknown, or the card has no power, exactly when cards.power is NULL or the literal '*'; values such as '1+*' are real, known powers.  (applies to: unknown power, without power, no power, cards without power, powerless)
f20 score +0 uses 0 [mapping] cards.types: A card type named in a question (e.g. Creature, Artifact) matches a whole element of the comma-separated cards.types, or an exact cards.originalType value; cards.type is the full printed type line.  (applies to: card type, type Creature, Artifact cards, type of the card)
f21 score +0 uses 4 [relation] legalities.uuid: One legalities row is one card's status in one format, so banned status is per-format; rows match cards on uuid, and some cards have no legalities row so an inner join drops them.  (applies to: banned, is banned, legality, play format, banned status)
```

### Order 0, european_football_2: 11 facts, retired {'consolidated into f11': 2, 'regression while unproven': 1}

```
f1 score +0 uses 1 [encoding] date columns: All date columns (Player.birthday, Match.date, Player_Attributes.date, Team_Attributes.date) are text 'YYYY-MM-DD HH:MM:SS'; the year and month are its first seven characters.  (applies to: birthyear, birthmonth, match date month, attribute date range, season date)
f2 score +0 uses 1 [mapping] Match.season: Match.season holds spans like '2009/2010'; a season named by a single year YYYY means the span ending in that year (2010 -> '2009/2010'), not the span starting in it.  (applies to: 2010 season, the 2010 season, season named by year, Scotland Premier League 2010)
f3 score +0 uses 1 [mapping] age: A player's age means their age today: current year minus the year in Player.birthday, minus one if this year's birthday has not yet passed; never measured from Player_Attributes.date.  (applies to: player's age, age, how old is the player, sprint speed)
f4 score +1 uses 4 RETIRED (consolidated into f11) [relation] Player_Attributes.player_fifa_api_id: Each Player_Attributes row is one player's ratings snapshot on a date; a player named in a question is matched on Player.player_name and joined to these rows on player_fifa_api_id (or player_api_id), never a guessed id.  (applies to: average overall rating of a player, player name lookup, Marko Arnautovic, player attributes over a date range)
f5 score +0 uses 0 [relation] Player_Attributes.player_api_id: Some Player rows have no Player_Attributes rows at all, so shares like players with a high rating must be measured over players present in both tables, not over every Player row.  (applies to: percentage of players, players with overall rating greater than 70, players under 180 cm, players who have a record with rating above)
f6 score +0 uses 0 [grain] Player.player_api_id: Player.player_api_id uniquely identifies one player, while Player.player_name repeats across different players (e.g. several 'Danilo', 'Paulinho'); so players are grouped and counted by player_api_id, never by name alone.  (applies to: players' names, top 10 players, player name, distinct players, count players)
f7 score -1 uses 2 RETIRED (regression while unproven) [grain] Match.id: One Match row is one game, so a league's game count is the number of its Match rows linked by League.id = Match.league_id; leagues are grouped by League.name.  (applies to: most games, number of games, games in a season, top leagues, league fixtures)
f8 score +0 uses 0 RETIRED (consolidated into f11) [grain] Player_Attributes.player_api_id: Player_Attributes has one row per player per rating date, so player_api_id repeats many times; a player's rating records are all of those dated rows, not a single row.  (applies to: all records, finishing rate, curve score, player ratings, highest weight)
f9 score +0 uses 0 [mapping] Player.height: Player.height values tie heavily across players, so 'tallest players' means every player whose height equals the single maximum value, not a fixed top-N list.  (applies to: tallest players, players with the greatest height, top players by height, highest height)
f10 score +0 uses 0 [mapping] older player: Between the two players a question names, the older one is the row with the earlier Player.birthday text (YYYY-MM-DD...); no age arithmetic or other tables are involved.  (applies to: which player is older, older, younger, player name, birthday)
f11 score +1 uses 5 [relation] Player_Attributes.player_api_id: Player_Attributes holds one row per player per rating date, so player_api_id repeats; a player named in a question is matched on Player.player_name and joined on player_api_id or player_fifa_api_id, never a guessed id.  (applies to: average overall rating of a player, all records, player name lookup, player attributes over a date range, player ratings)
```

## Pinned data

Arcwise commit `fe766045c55b6875a43b30e9ac7683df5582f8cf`; questions per database {'formula_1': 66, 'superhero': 52, 'card_games': 52, 'european_football_2': 51}.

```
baefe2ca4fbab86c  data/arcwise/arcwise_plat_full_with_diff.json
f588644176ffff50  data/arcwise/schemas/card_games/database_description/cards.csv
1116f337c671c7a2  data/arcwise/schemas/card_games/database_description/foreign_data.csv
46858a4678ab5281  data/arcwise/schemas/card_games/database_description/legalities.csv
e379ac1acabda8a1  data/arcwise/schemas/card_games/database_description/rulings.csv
625fbc0f567de1db  data/arcwise/schemas/card_games/database_description/set_translations.csv
d835acfb1dba48d9  data/arcwise/schemas/card_games/database_description/sets.csv
74c830da5768d7fc  data/arcwise/schemas/european_football_2/database_description/Country.csv
a3fefa1fb96a2732  data/arcwise/schemas/european_football_2/database_description/League.csv
71eb75bddb0609c5  data/arcwise/schemas/european_football_2/database_description/Match.csv
7e6410a6123f7d48  data/arcwise/schemas/european_football_2/database_description/Player.csv
f9d6b83a468a8a1f  data/arcwise/schemas/european_football_2/database_description/Player_Attributes.csv
90abb432a781ab5e  data/arcwise/schemas/european_football_2/database_description/Team.csv
e563a447f07fc80b  data/arcwise/schemas/european_football_2/database_description/Team_Attributes.csv
6e5e4dc157ff5563  data/arcwise/schemas/formula_1/database_description/circuits.csv
49ce895dd0b76928  data/arcwise/schemas/formula_1/database_description/constructorResults.csv
b62bce2ee2c3b4cb  data/arcwise/schemas/formula_1/database_description/constructorStandings.csv
b411bc460b47ff27  data/arcwise/schemas/formula_1/database_description/constructors.csv
47d3223743113ddd  data/arcwise/schemas/formula_1/database_description/driverStandings.csv
bd6cb56fb4f210f0  data/arcwise/schemas/formula_1/database_description/drivers.csv
1640520cc0c1c3bf  data/arcwise/schemas/formula_1/database_description/lapTimes.csv
374bf554e7fd0f1e  data/arcwise/schemas/formula_1/database_description/pitStops.csv
e2151118433c6857  data/arcwise/schemas/formula_1/database_description/qualifying.csv
416d40040a33b960  data/arcwise/schemas/formula_1/database_description/races.csv
ff731a8d0206247e  data/arcwise/schemas/formula_1/database_description/results.csv
279ef8adafc837c6  data/arcwise/schemas/formula_1/database_description/seasons.csv
bc0c392ffe02e5e1  data/arcwise/schemas/formula_1/database_description/status.csv
ebff59e5832b2870  data/arcwise/schemas/superhero/database_description/alignment.csv
3c6bac9176d61e05  data/arcwise/schemas/superhero/database_description/attribute.csv
ba732eddb938dc07  data/arcwise/schemas/superhero/database_description/colour.csv
7311f964c77b6319  data/arcwise/schemas/superhero/database_description/gender.csv
65af1dfdb96e4dda  data/arcwise/schemas/superhero/database_description/hero_attribute.csv
54eb40baa6b5b726  data/arcwise/schemas/superhero/database_description/hero_power.csv
232e8656107f426b  data/arcwise/schemas/superhero/database_description/publisher.csv
8eb79fe0d1fc7d56  data/arcwise/schemas/superhero/database_description/race.csv
503f0a71acd17669  data/arcwise/schemas/superhero/database_description/superhero.csv
4edef8900f158238  data/arcwise/schemas/superhero/database_description/superpower.csv
17185981cd747f6c  data/bird_dev/formula_1/formula_1.sqlite
75e94a2c3236ee3b  data/bird_dev/superhero/superhero.sqlite
c98bdb57fe7474da  data/bird_dev/card_games/card_games.sqlite
e4d361dbeec6591a  data/bird_dev/european_football_2/european_football_2.sqlite
```
