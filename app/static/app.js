/* PeakAge Companion Academy — interactions. No libraries. */
(function () {
  "use strict";

  /* ---------- progress rings ---------- */
  function animateRings() {
    document.querySelectorAll(".ring[data-ring]").forEach(function (ring) {
      var pct = Math.max(0, Math.min(100, Number(ring.dataset.ring) || 0));
      var fill = ring.querySelector(".ring-fill");
      if (!fill) return;
      var len = 2 * Math.PI * 52;
      fill.style.strokeDasharray = len;
      fill.style.strokeDashoffset = len;
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          fill.style.strokeDashoffset = len * (1 - pct / 100);
        });
      });
      var counter = ring.querySelector("[data-count]");
      if (counter) {
        var target = Number(counter.dataset.count), start = null;
        var step = function (t) {
          if (!start) start = t;
          var p = Math.min((t - start) / 1100, 1);
          counter.textContent = Math.round(target * (1 - Math.pow(1 - p, 3))) + "%";
          if (p < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      }
    });
  }

  /* ---------- reading progress on lessons ---------- */
  function readingProgress() {
    var bar = document.querySelector(".read-progress div");
    if (!bar) return;
    var update = function () {
      var h = document.documentElement;
      var max = h.scrollHeight - h.clientHeight;
      bar.style.width = (max > 0 ? (h.scrollTop / max) * 100 : 100) + "%";
    };
    document.addEventListener("scroll", update, { passive: true });
    update();
  }

  /* ---------- confetti ---------- */
  function confetti() {
    if (!document.querySelector("[data-confetti]")) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    var canvas = document.getElementById("confetti");
    if (!canvas) return;
    var ctx = canvas.getContext("2d");
    var W = (canvas.width = window.innerWidth), H = (canvas.height = window.innerHeight);
    var colors = ["#D18E39", "#E9B46F", "#18212D", "#2F7D6D", "#F4D9B0"];
    var pieces = [];
    for (var i = 0; i < 160; i++) {
      pieces.push({
        x: W / 2 + (Math.random() - 0.5) * W * 0.3,
        y: H * 0.35,
        vx: (Math.random() - 0.5) * 14,
        vy: -Math.random() * 14 - 4,
        r: Math.random() * 6 + 4,
        c: colors[i % colors.length],
        a: Math.random() * Math.PI,
        va: (Math.random() - 0.5) * 0.3,
      });
    }
    var frames = 0;
    (function tick() {
      ctx.clearRect(0, 0, W, H);
      pieces.forEach(function (p) {
        p.vy += 0.35; p.vx *= 0.99; p.x += p.vx; p.y += p.vy; p.a += p.va;
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.a);
        ctx.fillStyle = p.c; ctx.fillRect(-p.r / 2, -p.r / 4, p.r, p.r / 2);
        ctx.restore();
      });
      if (++frames < 200) requestAnimationFrame(tick);
      else ctx.clearRect(0, 0, W, H);
    })();
  }

  /* ---------- interactive quiz: one question at a time, instant feedback ---------- */
  function quiz() {
    var form = document.getElementById("quiz");
    if (!form) return;
    var attemptId = form.dataset.attempt;
    var cards = Array.prototype.slice.call(form.querySelectorAll(".question"));
    var total = cards.length;
    var currentEl = document.getElementById("q-current");
    var scoreEl = document.getElementById("q-score");
    var barEl = document.getElementById("q-bar");

    function answeredCount() { return form.querySelectorAll(".question.is-answered").length; }
    function score() { return form.querySelectorAll(".question.is-right").length; }
    function refreshMeter(index) {
      if (currentEl) currentEl.textContent = Math.min(index + 1, total);
      if (scoreEl) scoreEl.textContent = score();
      if (barEl) barEl.style.width = (answeredCount() / total) * 100 + "%";
    }
    function show(index) {
      cards.forEach(function (c, i) { c.classList.toggle("is-current", i === index); });
      refreshMeter(index);
      var top = form.getBoundingClientRect().top + window.scrollY - 90;
      if (window.scrollY > top) window.scrollTo({ top: top, behavior: "smooth" });
    }

    // start at the first unanswered question (an attempt can be resumed)
    var first = cards.findIndex(function (c) { return !c.classList.contains("is-answered"); });
    show(first === -1 ? total - 1 : first);

    cards.forEach(function (card, index) {
      var qid = card.dataset.qid;
      var radios = card.querySelectorAll("input[type=radio]");
      var next = card.querySelector(".q-next");
      var fb = card.querySelector(".feedback");

      radios.forEach(function (radio) {
        radio.addEventListener("change", function () {
          if (card.classList.contains("is-answered") || card.classList.contains("is-pending")) return;
          card.classList.add("is-pending");
          radios.forEach(function (r) { r.disabled = true; });
          fetch("/api/attempts/" + attemptId + "/answer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ question_id: qid, choice: Number(radio.value) }),
          })
            .then(function (res) { return res.json().then(function (j) { return { ok: res.ok, j: j }; }); })
            .then(function (r) {
              card.classList.remove("is-pending");
              if (!r.ok) {
                alert(r.j.error || "Something went wrong. Please reload the page.");
                window.location.reload();
                return;
              }
              var res = r.j;
              card.classList.add("is-answered", res.correct ? "is-right" : "is-wrong");
              radios.forEach(function (rr) {
                var label = rr.closest(".option");
                var v = Number(rr.value);
                if (v === res.correct_choice) label.classList.add("opt-correct");
                if (v === res.choice && !res.correct) label.classList.add("opt-wrong");
                rr.checked = v === res.choice;
              });
              fb.hidden = false;
              fb.querySelector(".feedback-title").textContent = res.correct ? "Sahi jawab! ✓" : "Not quite ✗";
              fb.querySelector(".feedback-text").textContent = res.explanation || "";
              next.disabled = false;
              refreshMeter(index);
              if (navigator.vibrate) navigator.vibrate(res.correct ? 30 : [40, 60, 40]);
            })
            .catch(function () {
              card.classList.remove("is-pending");
              radios.forEach(function (r) { r.disabled = false; r.checked = false; });
              alert("No internet connection. Please try again.");
            });
        });
      });

      next.addEventListener("click", function () {
        if (index + 1 < total) {
          show(index + 1);
        } else {
          next.disabled = true;
          next.textContent = "Calculating…";
          form.submit();
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    animateRings();
    readingProgress();
    quiz();
    confetti();
  });
})();
