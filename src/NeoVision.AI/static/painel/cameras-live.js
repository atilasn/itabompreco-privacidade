/* NeoVision · lista GET /cameras + estado por probe RTSP · partilhado páginas Câmeras e Tempo real */
(function () {
  function delay(ms) {
    return new Promise(function (r) {
      setTimeout(r, ms);
    });
  }

  /** Texto unificado de `detail` (string, array OWASP, objeto). */
  function flattenDetail(detail) {
    if (detail == null || detail === "") return "";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail))
      return detail
        .map(function (x) {
          return (x.msg != null ? String(x.msg) : "") + "";
        })
        .join(" ");
    try {
      return JSON.stringify(detail);
    } catch (_e) {
      return String(detail);
    }
  }

  /** Base indisponível / MySQL offline – não inundar o painel com JSON técnico. */
  function isDbUnreachable(httpStatus, detailText) {
    if (httpStatus === 503) return true;
    var t = String(detailText || "");
    return (
      /can't connect to mysql|não foi possível ligar ao mysql|neovision_mysql|neo_vision_mysql|mysql\.server|127\.0\.0\.1|3306|winerror 10061|refused actively/i.test(
        t,
      )
    );
  }

  async function probeOne(id) {
    var idStr = String(id || "");
    if (!idStr) return { ok: false, online: false, last_error: "id inválido" };
    try {
      var res = await fetch(
        "/cameras/" + encodeURIComponent(idStr) + "/status?probe=true",
        { headers: { Accept: "application/json" } }
      );
      var st = await res.json().catch(function () {
        return null;
      });
      if (!res.ok) {
        var rawDetail = st ? flattenDetail(st.detail) : "";
        if (isDbUnreachable(res.status, rawDetail)) {
          return { ok: false, online: false, suppressed: true };
        }
        var detail = "Erro ao ler estado.";
        if (rawDetail) detail = rawDetail.length > 180 ? rawDetail.slice(0, 180) + "…" : rawDetail;
        return { ok: false, online: false, last_error: detail };
      }
      return {
        ok: true,
        online: !!st.online,
        last_error: st.last_error,
        last_seen_utc: st.last_seen_utc,
      };
    } catch (e) {
      return { ok: false, online: false, last_error: String(e.message || e) };
    }
  }

  /** Vários probe=true em paralelo pequenos para não bloquear o servidor por muito tempo. */
  async function probeAll(list, concurrency) {
    var n = concurrency || 3;
    var map = {};
    var i = 0;
    while (i < list.length) {
      var slice = list.slice(i, i + n);
      await Promise.all(
        slice.map(function (cam) {
          return probeOne(cam.id).then(function (p) {
            map[cam.id] = p;
          });
        })
      );
      i += n;
      if (i < list.length) await delay(150);
    }
    return map;
  }

  /**
   * @returns {Promise<{ok:boolean, list?:[], byId?:Object, error?:string}>}
   */
  async function fetchListWithStatuses() {
    var r = await fetch("/cameras");
    if (!r.ok) {
      var txt = await r.text().catch(function () {
        return "";
      });
      var body = {};
      try {
        body = txt ? JSON.parse(txt) : {};
      } catch (_e) {
        body = {};
      }
      var merged = flattenDetail(body.detail);
      if (!merged && txt && txt.slice(0, 1) === "{") merged = txt;
      if (isDbUnreachable(r.status, merged))
        return { ok: true, list: [], byId: {} };
      return {
        ok: false,
        error:
          merged && merged.length <= 200
            ? merged.slice(0, 200) + (merged.length > 200 ? "…" : "")
            : "Lista indisponível.",
      };
    }
    var list = await r.json().catch(function () {
      return [];
    });
    if (!Array.isArray(list)) list = [];
    var byId = await probeAll(list, 3);
    return { ok: true, list: list, byId: byId };
  }

  window.NeoVisionCamerasLive = {
    probeOne: probeOne,
    probeAllStatuses: probeAll,
    fetchListWithStatuses: fetchListWithStatuses,
  };
})();
