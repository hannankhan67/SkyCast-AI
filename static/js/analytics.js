/* SkyCast AI — Analytics page "live tail"
   Appends rotating HDFS/MapReduce/Flask log lines after the CSS cascade. */
(function () {
  "use strict";
  var cursor = document.getElementById("term-cursor");
  if (!cursor) return;

  var pool = [
    '<span class="text-yellow-400">[SYSTEM]</span> Heartbeat OK — datanode-03 (rack-1)',
    '<span class="text-cyan-400">[HDFS]</span> Replicating block bp-1024 → 2 datanodes',
    '<span class="text-purple-400">[ANALYTICS]</span> Anomaly flagged in record KHI-44812',
    '<span class="text-emerald-400">[FLASK]</span> /api/weather → 200 OK · 32ms',
    '<span class="text-cyan-400">[HDFS]</span> MapReduce job_20260829_0017 — 100% complete',
    '<span class="text-emerald-400">[OK]</span> Cluster healthy · 12/12 datanodes reporting',
  ];

  setTimeout(function () {
    var i = 0;
    setInterval(function () {
      var line = document.createElement("div");
      line.className = "log-live";
      line.innerHTML = pool[i % pool.length];
      cursor.parentNode.insertBefore(line, cursor);

      while (cursor.parentNode.children.length > 11) {
        var first = cursor.parentNode.querySelector(".log-live");
        if (first && first !== cursor) first.remove();
        else break;
      }
      i += 1;
    }, 2600);
  }, 6500);
})();