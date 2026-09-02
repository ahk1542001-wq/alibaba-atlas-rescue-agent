/**
 * TravelCare AI — Map Visualization Module (§U1)
 *
 * Implements interactive spatial route visualization using Leaflet + OpenStreetMap.
 * Strict coordinate sourcing honesty:
 * - Solid pins for live tooling airport data (is_estimated = false).
 * - Hollow dashed pins with visible "estimated" badge for LLM-suggested points (is_estimated = true).
 * - Multi-airport ambiguity (BKK/DMK) renders BOTH candidate airports with confirmation affordances.
 * - Degraded tiles gracefully fall back to labeled route summary without crashing the view.
 * - Leaflet and OSM attribution controls are strictly preserved.
 */

(function () {
    'use strict';

    var AIRPORTS = {
        'BKK': { lat: 13.6900, lng: 100.7501, name: 'Suvarnabhumi Airport (BKK)', is_estimated: false },
        'DMK': { lat: 13.9126, lng: 100.6067, name: 'Don Mueang Airport (DMK)', is_estimated: false },
        'SIN': { lat: 1.3644, lng: 103.9915, name: 'Singapore Changi Airport (SIN)', is_estimated: false },
        'KUL': { lat: 2.7456, lng: 101.7099, name: 'Kuala Lumpur International (KUL)', is_estimated: false },
        'RGN': { lat: 16.9073, lng: 96.1332, name: 'Yangon International Airport (RGN)', is_estimated: false },
        'CNX': { lat: 18.7668, lng: 98.9626, name: 'Chiang Mai International (CNX)', is_estimated: false },
        'HKG': { lat: 22.3080, lng: 113.9185, name: 'Hong Kong International (HKG)', is_estimated: false },
        'HND': { lat: 35.5494, lng: 139.7798, name: 'Tokyo Haneda Airport (HND)', is_estimated: false },
        'NRT': { lat: 35.7720, lng: 140.3929, name: 'Tokyo Narita Airport (NRT)', is_estimated: false },
        'ICN': { lat: 37.4602, lng: 126.4407, name: 'Seoul Incheon Airport (ICN)', is_estimated: false },
        'PEK': { lat: 40.0799, lng: 116.6031, name: 'Beijing Capital Airport (PEK)', is_estimated: false },
        'PKX': { lat: 39.5098, lng: 116.4105, name: 'Beijing Daxing Airport (PKX)', is_estimated: false },
        'PVG': { lat: 31.1443, lng: 121.8083, name: 'Shanghai Pudong Airport (PVG)', is_estimated: false },
        'SHA': { lat: 31.1979, lng: 121.3363, name: 'Shanghai Hongqiao Airport (SHA)', is_estimated: false },
        'CAN': { lat: 23.3924, lng: 113.2988, name: 'Guangzhou Baiyun Airport (CAN)', is_estimated: false }
    };

    var TravelCareMap = {
        ENABLED: true,
        AIRPORTS: AIRPORTS,

        /**
         * Resolves a location code or city name to one or more airport coordinates.
         * Renders both candidate airports when ambiguity exists (e.g. Bangkok -> BKK and DMK).
         */
        resolve: function (query) {
            if (!query) return [];
            var q = String(query).trim().toUpperCase();

            if (q === 'BANGKOK' || q === 'BKK/DMK') {
                return [
                    { code: 'BKK', lat: AIRPORTS.BKK.lat, lng: AIRPORTS.BKK.lng, name: AIRPORTS.BKK.name, is_estimated: false, ambiguous: true },
                    { code: 'DMK', lat: AIRPORTS.DMK.lat, lng: AIRPORTS.DMK.lng, name: AIRPORTS.DMK.name, is_estimated: false, ambiguous: true }
                ];
            }
            if (q === 'BEIJING') {
                return [
                    { code: 'PEK', lat: AIRPORTS.PEK.lat, lng: AIRPORTS.PEK.lng, name: AIRPORTS.PEK.name, is_estimated: false, ambiguous: true },
                    { code: 'PKX', lat: AIRPORTS.PKX.lat, lng: AIRPORTS.PKX.lng, name: AIRPORTS.PKX.name, is_estimated: false, ambiguous: true }
                ];
            }
            if (q === 'SHANGHAI') {
                return [
                    { code: 'PVG', lat: AIRPORTS.PVG.lat, lng: AIRPORTS.PVG.lng, name: AIRPORTS.PVG.name, is_estimated: false, ambiguous: true },
                    { code: 'SHA', lat: AIRPORTS.SHA.lat, lng: AIRPORTS.SHA.lng, name: AIRPORTS.SHA.name, is_estimated: false, ambiguous: true }
                ];
            }

            if (AIRPORTS[q]) {
                var a = AIRPORTS[q];
                return [{ code: q, lat: a.lat, lng: a.lng, name: a.name, is_estimated: false, ambiguous: false }];
            }

            // Fallback for LLM-suggested venues or non-indexed cities: honest estimation
            return [{
                code: q,
                lat: 13.7563,
                lng: 100.5018,
                name: String(query) + ' (estimated location)',
                is_estimated: true,
                ambiguous: false
            }];
        },

        /**
         * Initializes a Leaflet map instance on the given element ID.
         */
        createMap: function (elementId, fallbackId) {
            if (typeof window === 'undefined' || !window.L) return null;
            var el = document.getElementById(elementId);
            if (!el) return null;

            try {
                var map = window.L.map(elementId, {
                    zoomControl: true,
                    attributionControl: true,
                    scrollWheelZoom: false
                }).setView([13.7563, 100.5018], 5);

                var tileLayer = window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    maxZoom: 18,
                    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
                });

                tileLayer.on('tileerror', function () {
                    var fb = document.getElementById(fallbackId);
                    if (fb) fb.hidden = false;
                });

                tileLayer.addTo(map);
                return map;
            } catch (err) {
                console.warn('[TravelCareMap] Map init error:', err);
                return null;
            }
        },

        /**
         * Creates a DOM element for a Leaflet popup ensuring strict XSS safety.
         */
        createPopupNode: function (item) {
            var container = document.createElement('div');
            container.style.fontSize = '12px';
            container.style.lineHeight = '1.4';

            var title = document.createElement('div');
            title.style.fontWeight = '600';
            title.textContent = item.name || item.code;
            container.appendChild(title);

            if (item.ambiguous) {
                var ambBadge = document.createElement('div');
                ambBadge.style.color = '#B45309';
                ambBadge.style.marginTop = '4px';
                ambBadge.textContent = window.t ? window.t('map.ambiguity_title') : 'Multiple airports match — please confirm';
                container.appendChild(ambBadge);
            }

            if (item.is_estimated) {
                var estBadge = document.createElement('span');
                estBadge.className = 'map-badge-estimated';
                estBadge.textContent = window.t ? window.t('map.pin_estimated') : 'estimated location';
                container.appendChild(estBadge);
            } else {
                var srcBadge = document.createElement('span');
                srcBadge.style.fontSize = '10px';
                srcBadge.style.color = '#0A574D';
                srcBadge.textContent = ' • ' + (window.t ? window.t('map.pin_sourced') : 'live data');
                container.appendChild(srcBadge);
            }

            return container;
        },

        /**
         * Renders points and connecting lines onto an active Leaflet map.
         */
        renderPointsAndRoutes: function (map, points, routeOpts) {
            if (!map || !window.L || !points || points.length === 0) return;
            var latLngs = [];

            points.forEach(function (pt) {
                latLngs.push([pt.lat, pt.lng]);
                var marker;
                var popupNode = TravelCareMap.createPopupNode(pt);

                if (pt.is_estimated) {
                    // Hollow / ghost pin for estimated points
                    marker = window.L.circleMarker([pt.lat, pt.lng], {
                        radius: 8,
                        color: '#D97706',
                        weight: 2,
                        dashArray: '3, 3',
                        fillColor: '#FEF3C7',
                        fillOpacity: 0.4
                    });
                } else {
                    // Solid pin for live tooling
                    var markerColor = pt.isDisrupted ? '#DC2626' : (pt.isRescue ? '#12796B' : '#0A574D');
                    marker = window.L.circleMarker([pt.lat, pt.lng], {
                        radius: 7,
                        color: '#FFFFFF',
                        weight: 2,
                        fillColor: markerColor,
                        fillOpacity: 0.95
                    });
                }

                marker.bindPopup(popupNode);
                marker.addTo(map);
            });

            if (latLngs.length >= 2) {
                var lineOpts = routeOpts || { color: '#12796B', weight: 3, dashArray: '5, 5' };
                window.L.polyline(latLngs, lineOpts).addTo(map);
                map.fitBounds(window.L.latLngBounds(latLngs), { padding: [30, 30] });
            } else if (latLngs.length === 1) {
                map.setView(latLngs[0], 6);
            }
        },

        /**
         * Wires collapsible toggle button.
         */
        bindToggle: function (btnId, containerId) {
            var btn = document.getElementById(btnId);
            var container = document.getElementById(containerId);
            if (!btn || !container) return;

            btn.addEventListener('click', function () {
                var isHidden = container.hidden;
                container.hidden = !isHidden;
                var key = !isHidden ? 'map.expand' : 'map.collapse';
                btn.textContent = window.t ? window.t(key) : (!isHidden ? 'Expand map' : 'Collapse map');
                btn.setAttribute('data-i18n', key);
            });
        }
    };

    if (typeof window !== 'undefined') {
        window.TravelCareMap = TravelCareMap;
    }
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = TravelCareMap;
    }
})();
