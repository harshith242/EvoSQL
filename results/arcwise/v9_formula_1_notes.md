Working notes about this database:
## Joins and keys
- To find which races a driver took part in, join races to driverStandings on raceId; that table holds one row per driver per race.
## Time and dates
- Birth years are compared by extracting the year with STRFTIME('%Y', dob) against a year string, not by comparing dob to a full date literal.
- Age questions derive a computed age from dob against the current date: year difference minus one when this year's birthday has not yet passed, returned as its own column.
## Values and naming
- Driver names are split into forename and surname columns; always filter both separately instead of guessing or hardcoding a driverId value.
- Pit stop lengths are stored twice: duration as seconds in text form and a separate whole-millisecond column; average the seconds column so results stay in seconds.
- Completing a race shows as non-null results.time or a 'Finished' status, while wording about finishing first is judged by results.position, never by time.
- A driver credited with a race's fastest lap is flagged by non-null results.fastestLapTime or fastestLap, not results.rank or lapTimes; multi-race records are the minimum fastestLapTime.
- fastestLapSpeed and duration CAST straight to REAL, but minute:second.millisecond values (q1/q2/q3, fastestLapTime) need minutes*60 + seconds parsed out before ranking.
- Qualifying session times in q1/q2/q3 are stored as minute:second.millisecond text with no leading hour zero, so match a given clock time by LIKE on its minute:second prefix.
- A driver's country or nationality is drivers.nationality; circuits.country describes venues only, so driver-country questions never join the circuits table.
## Answer shape
- Percentage answers return full precision: COUNT(IIF(condition, id, NULL)) * 100.0 / COUNT(id) cast to REAL, never wrapped in ROUND.
- Rate-style denominators count result rows in the filtered period, one per race-and-driver combination, not distinct drivers or races.
- Superlative age questions order by dob (DESC for youngest, ASC for oldest) with LIMIT 1 and return every requested attribute, such as computed age plus name, as separate columns.
- Ranking questions select only the requested identifying columns and drop the aggregate used for ordering, even though that aggregate appears in ORDER BY.
- Maximum or fastest-value questions return the stored column of one extreme row: ORDER BY that column DESC with LIMIT 1, never an aggregate like MAX wrapped around it.
- Superlative 'in which ...' questions expecting multiple answers return all rows tied at the extreme value via an equality filter, not ORDER BY with LIMIT 1.
- When a question asks for a season's page, link, or url, return only that url column, not extra identifying columns like the year used to locate it.
## Traps
- A driver's position or 'track number' constraint refers to driverStandings.position, not results.grid or results.position, which are starting and finishing spots.
- Superlative queries filter IS NOT NULL on the ordering column itself, including near-full date columns like dob, because NULLs sort first and would otherwise be returned.
- Race-number bounds in questions can map to raceId with strict endpoints; mirror the phrasing's exclusivity instead of defaulting to an inclusive BETWEEN.
- Both qualifying and drivers have a number column; when a question asks a driver's own number, take drivers.number, not the qualifying row's number.
- Location words such as track or circuit never justify an invented circuitId, country, or venue filter unless the question names a real place.