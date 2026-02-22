(function () {
  'use strict';

  const DATA_URL = 'data/hundeskove.json';

  let map;
  let markersLayer;
  let geoData;

  function initMap() {
    map = L.map('map', {
      center: [56.0, 10.5],
      zoom: 7,
      zoomControl: true
    });
    L.control.zoom({ position: 'topright' }).addTo(map);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(map);

    markersLayer = L.layerGroup().addTo(map);
  }

  function formatSize(hectares) {
    if (hectares == null) return '–';
    if (hectares >= 1) {
      return hectares % 1 === 0
        ? hectares + ' ha'
        : hectares.toFixed(1) + ' ha';
    }
    return Math.round(hectares * 10000) + ' m²';
  }

  function renderForestList(features) {
    const listEl = document.getElementById('forest-list');
    const countEl = document.getElementById('forest-count');
    if (!listEl || !countEl) return;

    countEl.textContent = features.length;

    listEl.innerHTML = features
      .map(function (feature) {
        const p = feature.properties;
        const size = formatSize(p.size_hectares);
        return (
          '<li>' +
          '<button type="button" data-id="' + (p.id || '') + '" data-index="' + feature.index + '" aria-pressed="false">' +
          '<span class="forest-list-name">' + escapeHtml(p.name || 'Unavngivet') + '</span>' +
          '<span class="forest-list-size">' + size + ' · ' + escapeHtml(p.address || '') + '</span>' +
          '</button>' +
          '</li>'
        );
      })
      .join('');

    listEl.querySelectorAll('button').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const index = parseInt(btn.getAttribute('data-index'), 10);
        focusForest(index);
        listEl.querySelectorAll('button').forEach(function (b) { b.setAttribute('aria-pressed', 'false'); });
        btn.setAttribute('aria-pressed', 'true');
      });
    });
  }

  function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function createPopupContent(properties) {
    const size = formatSize(properties.size_hectares);
    const features = (properties.features && properties.features.length)
      ? properties.features.slice(0, 3).join(', ') + (properties.features.length > 3 ? '…' : '')
      : '–';
    return (
      '<strong>' + escapeHtml(properties.name || 'Unavngivet') + '</strong><br>' +
      escapeHtml(properties.address || '') + '<br>' +
      size + ' · ' + escapeHtml(features)
    );
  }

  function showDetailPanel(properties) {
    const panel = document.getElementById('detail-panel');
    const content = document.getElementById('detail-content');
    if (!panel || !content) return;

    const size = formatSize(properties.size_hectares);
    const featuresList = (properties.features && properties.features.length)
      ? properties.features.map(function (f) { return '<li>' + escapeHtml(f) + '</li>'; }).join('')
      : '<li>Ingen faciliteter angivet</li>';

    content.innerHTML =
      '<h2>' + escapeHtml(properties.name || 'Unavngivet') + '</h2>' +
      '<p class="detail-address">' + escapeHtml(properties.address || '') + '</p>' +
      '<p class="detail-size">Størrelse: ' + size + '</p>' +
      '<p><strong>Faciliteter</strong></p>' +
      '<ul class="detail-features">' + featuresList + '</ul>' +
      (properties.description ? '<p class="detail-description">' + escapeHtml(properties.description) + '</p>' : '');

    panel.classList.remove('hidden');
  }

  function hideDetailPanel() {
    const panel = document.getElementById('detail-panel');
    if (panel) panel.classList.add('hidden');
  }

  function focusForest(index) {
    const feature = geoData.features[index];
    if (!feature) return;

    const coords = feature.geometry.coordinates;
    const lat = coords[1];
    const lon = coords[0];
    map.setView([lat, lon], 14);

    markersLayer.eachLayer(function (layer) {
      if (layer.featureIndex === index) {
        layer.openPopup();
      }
    });

    showDetailPanel(feature.properties);
  }

  function addMarkers() {
    markersLayer.clearLayers();
    const features = geoData.features;

    features.forEach(function (feature, index) {
      feature.index = index;
      const coords = feature.geometry.coordinates;
      const lat = coords[1];
      const lon = coords[0];
      const props = feature.properties;

      const marker = L.marker([lat, lon])
        .bindPopup(createPopupContent(props), { maxWidth: 280 })
        .addTo(markersLayer);
      marker.featureIndex = index;

      marker.on('click', function () {
        showDetailPanel(props);
        document.querySelectorAll('#forest-list button').forEach(function (b) {
          b.setAttribute('aria-pressed', b.getAttribute('data-index') === String(index) ? 'true' : 'false');
        });
      });
    });

    if (features.length > 1) {
      const group = L.featureGroup(markersLayer.getLayers());
      map.fitBounds(group.getBounds().pad(0.15));
    } else if (features.length === 1) {
      const c = features[0].geometry.coordinates;
      map.setView([c[1], c[0]], 12);
    }

    renderForestList(features);
  }

  function loadData() {
    fetch(DATA_URL)
      .then(function (res) {
        if (!res.ok) throw new Error('Kunne ikke hente data: ' + res.status);
        return res.json();
      })
      .then(function (data) {
        if (!data.features || !Array.isArray(data.features)) {
          throw new Error('Ugyldig dataformat');
        }
        geoData = data;
        addMarkers();
      })
      .catch(function (err) {
        console.error(err);
        document.getElementById('forest-count').textContent = '0';
        document.getElementById('forest-list').innerHTML =
          '<li style="padding: 1rem; color: #999;">Kunne ikke indlæse hundeskove. Tjek at data/hundeskove.json findes.</li>';
      });
  }

  function init() {
    initMap();
    loadData();

    var closeBtn = document.getElementById('detail-close');
    if (closeBtn) closeBtn.addEventListener('click', hideDetailPanel);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
