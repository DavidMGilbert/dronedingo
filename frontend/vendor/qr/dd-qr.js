/* DroneDingo QR helper — wraps qrcode-generator to emit an inline SVG string. */
(function () {
  function svg(text, size) {
    try {
      var qr = qrcode(0, "M");        // auto type, medium error correction
      qr.addData(text); qr.make();
      var n = qr.getModuleCount(), cell = (size || 120) / n, out = "";
      for (var r = 0; r < n; r++) for (var c = 0; c < n; c++) {
        if (qr.isDark(r, c))
          out += '<rect x="' + (c * cell) + '" y="' + (r * cell) + '" width="' + cell + '" height="' + cell + '"/>';
      }
      return '<svg xmlns="http://www.w3.org/2000/svg" width="' + size + '" height="' + size +
        '" viewBox="0 0 ' + size + ' ' + size + '" fill="#0b1416">' + out + '</svg>';
    } catch (e) { return '<span style="font-size:11px;color:#a00">QR error</span>'; }
  }
  window.DDQR = { svg: svg };
})();
