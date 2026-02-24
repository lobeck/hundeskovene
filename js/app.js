(function () {
  'use strict';

  const DATA_URL = 'data/hundeskove.json';
  const SUPPORTED_LANGS = ['da', 'en', 'de'];
  const DEFAULT_LANG = 'da';

  let map;
  let forestsLayer;
  let geoData;
  let locale = {};
  let currentLang = DEFAULT_LANG;
  let currentDetailIndex = -1;

  function getStoredLang() {
    try {
      var stored = localStorage.getItem('hundeskov-lang');
      if (stored && SUPPORTED_LANGS.indexOf(stored) !== -1) return stored;
    } catch (e) {}
    return null;
  }

  function setStoredLang(lang) {
    try {
      localStorage.setItem('hundeskov-lang', lang);
    } catch (e) {}
  }

  function t(key) {
    var parts = key.split('.');
    var v = locale;
    for (var i = 0; i < parts.length; i++) {
      v = v && v[parts[i]];
    }
    return v != null ? String(v) : key;
  }

  function loadLocale(lang) {
    return fetch('locales/' + lang + '.json')
      .then(function (res) {
        if (!res.ok) throw new Error('Locale not found');
        return res.json();
      })
      .then(function (data) {
        locale = data;
        currentLang = lang;
        setStoredLang(lang);
        return data;
      });
  }

  function applyUiStrings() {
    document.documentElement.lang = currentLang === 'da' ? 'da' : currentLang === 'de' ? 'de' : 'en';
    if (document.title !== undefined) document.title = t('ui.title');
    var titleEl = document.getElementById('ui-title');
    var taglineEl = document.getElementById('ui-tagline');
    var countLabel = document.getElementById('ui-forests-count');
    var listEl = document.getElementById('forest-list');
    var mapEl = document.getElementById('map');
    var closeBtn = document.getElementById('detail-close');
    if (titleEl) titleEl.textContent = t('ui.title');
    if (taglineEl) taglineEl.textContent = t('ui.tagline');
    if (countLabel) countLabel.textContent = t('ui.forests_count');
    if (listEl) listEl.setAttribute('aria-label', t('ui.list_label'));
    if (mapEl) mapEl.setAttribute('aria-label', t('ui.map_label'));
    if (closeBtn) closeBtn.setAttribute('aria-label', t('ui.close'));
    document.querySelectorAll('.lang-btn').forEach(function (btn) {
      var lang = btn.getAttribute('data-lang');
      btn.classList.toggle('active', lang === currentLang);
      btn.setAttribute('aria-pressed', lang === currentLang ? 'true' : 'false');
    });
    if (geoData && geoData.features) renderForestList(geoData.features);
    if (currentDetailIndex >= 0 && geoData && geoData.features[currentDetailIndex]) {
      showDetailPanel(geoData.features[currentDetailIndex].properties);
    }
  }

  function getFeatureLabels(featureKeys) {
    if (!featureKeys || !featureKeys.length) return [];
    return featureKeys.map(function (k) { return t('feature.' + k); });
  }

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

  function getPointRadius() {
    if (!map) return 6;
    var z = map.getZoom();
    if (z <= 8) return 3;
    if (z <= 11) return 4;
    if (z <= 13) return 5;
    return 6;
  }

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

    map.on('zoomend', function () {
      var r = getPointRadius();
      forestsLayer.eachLayer(function (layer) {
        if (layer.setRadius) layer.setRadius(r);
      });
    });
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
    var uHa = t('ui.unit_ha');
    var uSqm = t('ui.unit_sqm');
    if (hectares >= 1) {
      return hectares % 1 === 0
        ? hectares + ' ' + uHa
        : hectares.toFixed(1) + ' ' + uHa;
    }
    return Math.round(hectares * 10000) + ' ' + uSqm;
  }

  function renderForestList(features) {
    var listEl = document.getElementById('forest-list');
    var countEl = document.getElementById('forest-count');
    if (!listEl || !countEl) return;

    countEl.textContent = features.length;

    listEl.innerHTML = features
      .map(function (feature) {
        var p = feature.properties;
        var size = formatSize(p.size_hectares);
        return (
          '<li>' +
          '<button type="button" data-id="' + escapeHtml(p.id || '') + '" data-index="' + feature.index + '" aria-pressed="false">' +
          '<span class="forest-list-name">' + escapeHtml(p.name || '–') + '</span>' +
          '<span class="forest-list-size">' + size + ' · ' + escapeHtml(p.address || '') + '</span>' +
          '</button>' +
          '</li>'
        );
      })
      .join('');

    listEl.querySelectorAll('button').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var index = parseInt(btn.getAttribute('data-index'), 10);
        focusForest(index);
        listEl.querySelectorAll('button').forEach(function (b) { b.setAttribute('aria-pressed', 'false'); });
        btn.setAttribute('aria-pressed', 'true');
      });
    });
  }

  function escapeHtml(text) {
    if (!text) return '';
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function createPopupContent(properties) {
    var size = formatSize(properties.size_hectares);
    var labels = getFeatureLabels(properties.feature_keys);
    var featuresStr = labels.length ? labels.slice(0, 3).join(', ') + (labels.length > 3 ? '…' : '') : '–';
    return (
      '<strong>' + escapeHtml(properties.name || '–') + '</strong><br>' +
      escapeHtml(properties.address || '') + '<br>' +
      size + ' · ' + escapeHtml(featuresStr)
    );
  }

  function showDetailPanel(properties) {
    var panel = document.getElementById('detail-panel');
    var content = document.getElementById('detail-content');
    if (!panel || !content) return;

    var size = formatSize(properties.size_hectares);
    var labels = getFeatureLabels(properties.feature_keys);
    var featuresList = labels.length
      ? labels.map(function (f) { return '<li>' + escapeHtml(f) + '</li>'; }).join('')
      : '<li>' + escapeHtml(t('ui.no_facilities')) + '</li>';

    content.innerHTML =
      '<h2>' + escapeHtml(properties.name || '–') + '</h2>' +
      '<p class="detail-address">' + escapeHtml(properties.address || '') + '</p>' +
      '<p class="detail-size">' + escapeHtml(t('ui.size')) + ': ' + size + '</p>' +
      '<p><strong>' + escapeHtml(t('ui.facilities')) + '</strong></p>' +
      '<ul class="detail-features">' + featuresList + '</ul>' +
      (properties.description ? '<p class="detail-description">' + escapeHtml(properties.description) + '</p>' : '');

    panel.classList.remove('hidden');
  }

  function hideDetailPanel() {
    var panel = document.getElementById('detail-panel');
    if (panel) panel.classList.add('hidden');
  }

  function focusForest(index) {
    var feature = geoData.features[index];
    if (!feature) return;
    currentDetailIndex = index;

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
        layer = L.circleMarker([geom.coordinates[1], geom.coordinates[0]], {
          radius: getPointRadius(),
          color: forestStyle.color,
          weight: forestStyle.weight,
          fillColor: forestStyle.fillColor,
          fillOpacity: forestStyle.fillOpacity
        });
        layer.on('mouseover', function (e) {
          e.target.setStyle({ weight: forestStyleHover.weight, fillOpacity: forestStyleHover.fillOpacity });
          e.target.bringToFront();
        });
        layer.on('mouseout', function (e) {
          e.target.setStyle({ weight: forestStyle.weight, fillOpacity: forestStyle.fillOpacity });
        });
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
          currentDetailIndex = index;
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
    var lang = getStoredLang() || (navigator.language && navigator.language.slice(0, 2) === 'de' ? 'de' : navigator.language && navigator.language.slice(0, 2) === 'en' ? 'en' : 'da');
    if (SUPPORTED_LANGS.indexOf(lang) === -1) lang = DEFAULT_LANG;

    Promise.all([
      loadLocale(lang),
      fetch(DATA_URL).then(function (res) {
        if (!res.ok) throw new Error('Data load failed');
        return res.json();
      })
    ])
      .then(function (results) {
        var data = results[1];
        if (!data.features || !Array.isArray(data.features)) throw new Error('Invalid data');
        geoData = data;
        applyUiStrings();
        addForests();
      })
      .catch(function (err) {
        console.error(err);
        loadLocale(DEFAULT_LANG).then(function () {
          applyUiStrings();
          document.getElementById('forest-count').textContent = '0';
          document.getElementById('forest-list').innerHTML =
            '<li style="padding: 1rem; color: #999;">' + escapeHtml(t('ui.load_error')) + '</li>';
        });
      });
  }

  function init() {
    initMap();

    document.querySelectorAll('.lang-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var lang = btn.getAttribute('data-lang');
        if (lang === currentLang) return;
        loadLocale(lang).then(function () {
          applyUiStrings();
          if (forestsLayer && geoData) {
            forestsLayer.eachLayer(function (layer) {
              if (layer.featureIndex != null && geoData.features[layer.featureIndex]) {
                layer.setPopupContent(createPopupContent(geoData.features[layer.featureIndex].properties));
              }
            });
          }
        });
      });
    });

    var closeBtn = document.getElementById('detail-close');
    if (closeBtn) closeBtn.addEventListener('click', function () {
      currentDetailIndex = -1;
      hideDetailPanel();
    });

    loadData();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
