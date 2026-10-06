// 03: Xiaohei pulls the 2 closest solved questions from a cabinet and pins them on the prompt board,
// next to the notes sheet that is always there.

// The cabinet of solved earlier questions.
rect(120, 420, 300, 420, { strokeWidth: 2.4 });
for (let i = 0; i < 3; i++) {
  rect(140, 440 + i * 135, 260, 115, { strokeWidth: 1.8 });
  line(240, 495 + i * 135, 300, 495 + i * 135, { strokeWidth: 3 });
}
for (let i = 0; i < 6; i++) rect(150 + i * 38, 380 - (i % 2) * 14, 32, 60, { fill: "#fff", fillStyle: "solid", strokeWidth: 1.4 });
label(270, 260, "similar()", "search.py", "2 closest solved");

// Xiaohei carries two solved questions (question + correct SQL) to the board.
sheet(500, 470, 90, 110, 3, { stroke: ORANGE, strokeWidth: 2.4 });
sheet(655, 460, 90, 110, 3, { stroke: ORANGE, strokeWidth: 2.4 });
xiaohei(620, 840, 1.6, [[560, 575], [680, 568]], [[590, 840], [650, 840]]);
arrow([[430, 520], [470, 440], [520, 455]], { stroke: ORANGE, strokeWidth: 3 });
arrow([[780, 640], [880, 600], [960, 620]], { stroke: ORANGE, strokeWidth: 3 });
label(640, 930, "examples_notes", "search.py", "question + correct SQL", ORANGE);

// The prompt board the agent reads.
rect(990, 330, 790, 560, { strokeWidth: 2.6 });
line(1040, 890, 1010, 960); line(1730, 890, 1760, 960);

// Column profile: in every prompt, for every memory type.
sheet(1020, 360, 200, 120, 4);
label(1120, 530, "value_profile", "bird.py", "in every prompt");

// The two pinned examples.
sheet(1040, 620, 150, 200, 6, { stroke: ORANGE, strokeWidth: 2.6 });
sheet(1210, 610, 150, 200, 6, { stroke: ORANGE, strokeWidth: 2.6 });
circle(1115, 628, 14, { fill: RED, fillStyle: "solid", stroke: RED }); circle(1285, 618, 14, { fill: RED, fillStyle: "solid", stroke: RED });

// The notes sheet: five sections, at most 100 lines, always pinned.
rect(1420, 360, 320, 500, { fill: "#fff", fillStyle: "solid", stroke: BLUE, strokeWidth: 2.8 });
const sections = ["Joins and keys", "Time and dates", "Values and naming", "Answer shape", "Traps"];
sections.forEach((s, i) => {
  text(1440, 410 + i * 92, "## " + s, 27, BLUE, "start", 700);
  line(1450, 432 + i * 92, 1700, 432 + i * 92, { stroke: "#9bb6dd", strokeWidth: 1.4 });
  line(1450, 456 + i * 92, 1650, 456 + i * 92, { stroke: "#9bb6dd", strokeWidth: 1.4 });
});
label(1580, 230, "Notes", "notes.py", "≤ 100 lines, always shown", BLUE);
label(1200, 960, "notes_text", "stream.py", "examples, then notes");

shift(90);
done();
