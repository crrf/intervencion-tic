/* =========================================================================
   Interacciones del tablero. El servidor es siempre la autoridad: aqui solo
   se decide que se puede arrastrar y a donde, para no mandar peticiones que
   se sabe que van a ser rechazadas.
   ========================================================================= */
(function () {
  "use strict";

  window.__arrastrando = false;

  function token() {
    var meta = document.querySelector("meta[name=csrf-token]");
    return meta ? meta.getAttribute("content") : "";
  }

  /** Transiciones que el servidor autorizo para esta tarjeta. */
  function transiciones(tarjeta) {
    var crudo = tarjeta.getAttribute("data-transiciones") || "";
    return crudo.split("|").filter(Boolean).map(function (item) {
      var partes = item.split("~");
      return { clave: partes[0], pideDatos: partes[1] === "1" };
    });
  }

  function transicionHacia(tarjeta, destino) {
    var campo = tarjeta.getAttribute("data-campo") || "estado";
    var buscada = campo + ":" + destino;
    return transiciones(tarjeta).find(function (t) { return t.clave === buscada; });
  }

  /**
   * El servidor redibuja el tablero completo con la respuesta, y para eso
   * necesita los mismos filtros que tiene la vista (busqueda, orden, columna
   * ampliada...). Van en la barra de direcciones, asi que se le reenvian.
   */
  function conFiltros(url) {
    var filtros = window.location.search;
    if (!filtros || filtros === "?") { return url; }
    return url + (url.indexOf("?") === -1 ? "?" : "&") + filtros.slice(1);
  }

  function enviar(url, datos) {
    url = conFiltros(url);
    var cuerpo = new URLSearchParams(datos);
    var destino = document.getElementById("tablero");
    destino.classList.add("htmx-request");
    fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRFToken": token(),
        "HX-Request": "true"
      },
      body: cuerpo,
      credentials: "same-origin"
    })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        destino.innerHTML = html;
        destino.classList.remove("htmx-request");
        iniciarTablero();
      })
      .catch(function () {
        destino.classList.remove("htmx-request");
        window.location.reload();
      });
  }

  /** Abre el modal que pide los datos que exige una transicion. */
  function abrirModal(url) {
    fetch(conFiltros(url), { headers: { "HX-Request": "true" }, credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        document.getElementById("modal").innerHTML = html;
      });
  }

  window.cerrarModal = function () {
    document.getElementById("modal").innerHTML = "";
  };

  /** Envia el formulario del modal y redibuja el tablero. */
  window.enviarModal = function (form) {
    var datos = {};
    new FormData(form).forEach(function (valor, clave) { datos[clave] = valor; });
    window.cerrarModal();
    enviar(form.getAttribute("action"), datos);
    return false;
  };

  function iniciarTablero() {
    var tablero = document.getElementById("tablero");
    if (!tablero || typeof Sortable === "undefined") { return; }

    tablero.querySelectorAll(".lista").forEach(function (lista) {
      Sortable.create(lista, {
        group: lista.getAttribute("data-grupo") || "tablero",
        animation: 140,
        ghostClass: "sortable-ghost",
        chosenClass: "sortable-chosen",
        filter: ".fija",
        // En pantalla tactil hay que mantener pulsado un momento para
        // arrastrar: sin esta espera, cualquier intento de desplazar la lista
        // con el dedo se lleva la tarjeta. Con raton no aplica.
        delay: 220,
        delayOnTouchOnly: true,
        touchStartThreshold: 5,
        onStart: function () { window.__arrastrando = true; },
        onEnd: function (evt) {
          window.__arrastrando = false;
          var origen = evt.from.getAttribute("data-estado");
          var destino = evt.to.getAttribute("data-estado");
          var tarjeta = evt.item;
          if (origen === destino) { return; }

          var permitida = transicionHacia(tarjeta, destino);
          if (!permitida) {
            // Se devuelve la tarjeta a su columna: el movimiento no aplica.
            evt.from.insertBefore(tarjeta, evt.from.children[evt.oldIndex] || null);
            avisar("Ese movimiento no esta permitido para tu perfil o para el estado actual.");
            return;
          }
          if (permitida.pideDatos) {
            evt.from.insertBefore(tarjeta, evt.from.children[evt.oldIndex] || null);
            abrirModal(tarjeta.getAttribute("data-url-accion") + "?transicion=" + encodeURIComponent(permitida.clave));
            return;
          }
          enviar(tarjeta.getAttribute("data-url-mover"), { transicion: permitida.clave });
        }
      });
    });
  }

  function avisar(mensaje) {
    var caja = document.querySelector(".avisos");
    if (!caja) { return; }
    var div = document.createElement("div");
    div.className = "aviso error";
    div.textContent = mensaje;
    caja.appendChild(div);
    setTimeout(function () { div.remove(); }, 6000);
  }
  window.avisar = avisar;

  /** Boton de accion dentro de una tarjeta o del detalle. */
  window.accionTicket = function (urlAccion, clave, urlMover, pideDatos) {
    if (pideDatos) {
      abrirModal(urlAccion + "?transicion=" + encodeURIComponent(clave));
    } else {
      enviar(urlMover, { transicion: clave });
    }
  };

  document.addEventListener("DOMContentLoaded", function () {
    iniciarTablero();
    // Los avisos flotantes se desvanecen solos.
    document.querySelectorAll(".avisos .aviso").forEach(function (el) {
      setTimeout(function () { el.remove(); }, 6000);
    });
  });

  // Tras cada intercambio de HTMX hay que volver a enganchar el drag & drop.
  document.body && document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.target && e.target.id === "tablero") { iniciarTablero(); }
  });
  document.addEventListener("htmx:afterSwap", function (e) {
    if (e.target && (e.target.id === "tablero")) { iniciarTablero(); }
  });

  // Cerrar el modal con Escape.
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { window.cerrarModal(); }
  });
})();
