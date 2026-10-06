// 01: questions ride a conveyor; Xiaohei answers first, then opens the correct-SQL envelope, then files the question.

// Conveyor belt with rollers.
line(60, 770, 1500, 770); line(60, 812, 1500, 812);
for (let x = 90; x < 1500; x += 120) circle(x, 791, 34, { strokeWidth: 1.6 });
arrow([[120, 650], [200, 640], [280, 650]], { stroke: ORANGE, strokeWidth: 3 });

// Incoming sealed question parcels.
for (const [x, q] of [[70, "q15"], [185, "q14"]]) {
  rect(x, 690, 92, 76, { fill: "#fff", fillStyle: "solid" });
  line(x, 712, x + 92, 712, { strokeWidth: 1.4 });
  text(x + 46, 752, q, 30);
}
label(180, 470, "run_stream", "stream.py", "one question at a time");

// Scene A: Xiaohei writes four answers to question 13 before anything is revealed.
line(330, 690, 760, 690, { strokeWidth: 2.6 }); line(350, 690, 350, 770); line(740, 690, 740, 770);
rect(345, 610, 90, 76, { fill: "#fff", fillStyle: "solid" }); line(345, 632, 435, 632, { strokeWidth: 1.4 });
text(390, 671, "q13", 30);
for (const [name, x] of [["none", 480], ["facts", 560], ["examples", 640], ["+notes", 720]]) {
  sheet(x - 25, 616, 50, 70, 3);
  text(x, 600, name, 25, "#444", "middle", 600);
}
xiaohei(830, 770, 1.6, [[730, 650], [760, 690]], [[805, 770], [855, 770]]);
line(728, 650, 718, 686, { strokeWidth: 2.6 });  // pen
label(560, 360, "answer()", "agent.py", "all 4 answer first", ORANGE);

// A thin wall: nothing about q13 is revealed until every answer is written.
line(940, 300, 940, 840, { stroke: "#999", strokeWidth: 1.5, strokeLineDash: [10, 12] });

// Scene B: Xiaohei pulls the correct SQL out of its envelope.
const ex = 1010, ey = 600;
poly([[ex, ey], [ex + 230, ey], [ex + 230, ey + 140], [ex, ey + 140]], { fill: "#fff", fillStyle: "solid" });
line(ex, ey, ex + 115, ey + 70); line(ex + 230, ey, ex + 115, ey + 70);
poly([[ex + 40, ey - 75], [ex + 220, ey - 82], [ex + 224, ey + 2], [ex + 44, ey + 8]],
     { fill: "#fff", fillStyle: "solid", stroke: ORANGE, strokeWidth: 2.8 });
text(ex + 132, ey - 30, "correct SQL", 34, ORANGE, "middle", 700);
xiaohei(1320, 770, 1.6, [[ex + 222, ey - 70], [ex + 226, ey - 10]], [[1295, 770], [1345, 770]]);
label(1125, 360, "gold_rows", "bird.py", "revealed after answering");

// Each answer is marked right or wrong against the correct rows.
text(1520, 590, "✓ ✗ ✓ ✓", 42, INK, "middle", 700);
label(1520, 430, "exec_match", "bird.py", "same rows = right");

// The answered question goes into the basket of earlier questions.
arrow([[1450, 660], [1560, 640], [1650, 650]], { stroke: ORANGE, strokeWidth: 3 });
path("M1600 680 L1780 680 L1755 820 L1625 820 Z", { strokeWidth: 2.4 });
for (let i = 0; i < 4; i++) rect(1630 + i * 34, 642 - (i % 2) * 10, 30, 40, { strokeWidth: 1.4 });
label(1690, 870, "observe", "memory.py", "kept for later questions");

// Memory only ever flows back to questions that come later.
arrow([[1620, 960], [1100, 1000], [560, 960], [500, 850]], { stroke: BLUE, strokeWidth: 2, strokeLineDash: [8, 10] });
text(1060, 1050, "only earlier questions feed the memory", 30, BLUE, "middle", 600);

shift(130);
done();
