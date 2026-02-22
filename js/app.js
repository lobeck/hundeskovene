(function () {
  'use strict';

  const DATA_URL = 'data/hundeskove.json';

  let map;
  let forestsLayer;
  let geoData;

  const forestStyle = {
    color: '#2d6a4f',
    weight: 2,
    fillColor: '#40916c',
    fillOpacity: 0.45
  };

  const forestStyleHover = {
    weight: 3,
    fillOpacity: 0.6
  };

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

    forestsLayer = L.layerGroup().addTo(map);
  }

  function getFeatureCenter(feature) {
    var geom = feature.geometry;
    if (geom.type === 'Point') {
      return L.latLng(geom.coordinates[1], geom.coordinates[0]);
    }
    if (geom.type === 'Polygon' && geom.coordinates[0] && geom.coordinates[0].length) {
      var ring = geom.coordinates[0];
      var sumLat = 0, sumLon = 0, n = ring.length - 1;
      for (var i = 0; i < n; i++) {
        sumLon += ring[i][0];
        sumLat += ring[i][1];
      }
      return L.latLng(sumLat / n, sumLon / n);
    }
    if (geom.type === 'MultiPolygon' && geom.coordinates[0] && geom.coordinates[0][0]) {
      var r = geom.coordinates[0][0];
      var sumLat = 0, sumLon = 0, n = r.length - 1;
      for (var i = 0; i < n; i++) {
        sumLon += r[i][0];
        sumLat += r[i][1];
      }
      return L.latLng(sumLat / n, sumLon / n);
    }
    return null;
  }

  function getFeatureBounds(feature) {
    var geom = feature.geometry;
    if (geom.type === 'Point') {
      var lat = geom.coordinates[1], lon = geom.coordinates[0];
      return L.latLngBounds([lat, lon], [lat, lon]);
    }
    if (geom.type === 'Polygon' && geom.coordinates[0]) {
      var lats = [], lons = [];
      geom.coordinates[0].forEach(function (c) {
        lons.push(c[0]);
        lats.push(c[1]);
      });
      return L.latLngBounds(
        [Math.min.apply(null, lats), Math.min.apply(null, lons)],
        [Math.max.apply(null, lats), Math.max.apply(null, lons)]
      );
    }
    if (geom.type === 'MultiPolygon') {
      var lats = [], lons = [];
      geom.coordinates.forEach(function (poly) {
        (poly[0] || []).forEach(function (c) {
          lons.push(c[0]);
          lats.push(c[1]);
        });
      });
      return L.latLngBounds(
        [Math.min.apply(null, lats), Math.min.apply(null, lons)],
        [Math.max.apply(null, lats), Math.max.apply(null, lons)]
      );
    }
    return null;
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
    var feature = geoData.features[index];
    if (!feature) return;

    var center = getFeatureCenter(feature);
    var bounds = getFeatureBounds(feature);
    if (bounds && bounds.isValid()) {
      map.fitBounds(bounds.pad(0.3), { maxZoom: 15 });
    } else if (center) {
      map.setView(center, 14);
    }

    forestsLayer.eachLayer(function (layer) {
      if (layer.featureIndex === index) {
        layer.openPopup();
      }
    });

    showDetailPanel(feature.properties);
  }

  function addForests() {
    forestsLayer.clearLayers();
    var features = geoData.features;

    features.forEach(function (feature, index) {
      feature.index = index;
      var props = feature.properties;
      var geom = feature.geometry;
      var layer;

      if (geom.type === 'Point') {
        layer = L.marker([geom.coordinates[1], geom.coordinates[0]]);
      } else if (geom.type === 'Polygon' || geom.type === 'MultiPolygon') {
        layer = L.geoJSON({ type: 'Feature', geometry: geom }, {
          style: forestStyle
        }).getLayers()[0];
        if (layer) {
          layer.on('mouseover', function (e) {
            e.target.setStyle(forestStyleHover);
            e.target.bringToFront();
          });
          layer.on('mouseout', function (e) {
            e.target.setStyle(forestStyle);
          });
        }
      }

      if (layer) {
        layer.featureIndex = index;
        layer.bindPopup(createPopupContent(props), { maxWidth: 280 });
        layer.on('click', function () {
          showDetailPanel(props);
          document.querySelectorAll('#forest-list button').forEach(function (b) {
            b.setAttribute('aria-pressed', b.getAttribute('data-index') === String(index) ? 'true' : 'false');
          });
        });
        forestsLayer.addLayer(layer);
      }
    });

    if (features.length > 1) {
      var allBounds = L.latLngBounds();
      features.forEach(function (f) {
        var b = getFeatureBounds(f);
        if (b && b.isValid()) allBounds.extend(b);
      });
      if (allBounds.isValid()) map.fitBounds(allBounds.pad(0.15));
    } else if (features.length === 1) {
      var c = getFeatureCenter(features[0]);
      var b = getFeatureBounds(features[0]);
      if (b && b.isValid()) map.fitBounds(b.pad(0.2));
      else if (c) map.setView(c, 12);
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
        addForests();
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
