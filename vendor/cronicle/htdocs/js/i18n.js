// Cronicle i18n - Lightweight internationalization
// Zero dependencies, key-value lookup with fallback

(function(window) {
	'use strict';

	var _strings = {};
	var _lang = 'en';
	var _fallback = {};
	var _ready = false;
	var _onReady = [];

	function _t(key) {
		var str = _strings[key] || _fallback[key] || key;
		if (arguments.length > 1) {
			for (var i = 1; i < arguments.length; i++) {
				str = str.replace('{' + (i - 1) + '}', arguments[i]);
			}
		}
		return str;
	}

	var I18n = {
		init: function(defaultLang) {
			_lang = localStorage.getItem('lang') ||
				(navigator.language && navigator.language.startsWith('zh') ? 'zh-TW' : '') ||
				defaultLang || 'en';

			// Always load English as fallback first
			this.load('en', function() {
				_fallback = JSON.parse(JSON.stringify(_strings));
				if (_lang === 'en') {
					_ready = true;
					I18n._fireReady();
				} else {
					I18n.load(_lang, function() {
						_ready = true;
						I18n._fireReady();
					});
				}
			});
		},

		load: function(lang, callback) {
			var xhr = new XMLHttpRequest();
			xhr.open('GET', 'js/lang/' + lang + '.json?v=' + (window.config_version || '1'), true);
			xhr.onreadystatechange = function() {
				if (xhr.readyState === 4) {
					if (xhr.status === 200) {
						try {
							_strings = JSON.parse(xhr.responseText);
						} catch(e) {
							console.warn('[i18n] Failed to parse ' + lang + '.json:', e);
						}
					} else {
						console.warn('[i18n] Failed to load ' + lang + '.json, status:', xhr.status);
					}
					if (callback) callback();
				}
			};
			xhr.send();
		},

		setLang: function(lang) {
			_lang = lang;
			localStorage.setItem('lang', lang);
			this.load(lang, function() {
				_ready = true;
				I18n.translateDOM();
				// Reload page to fully apply new language
				location.reload();
			});
		},

		getLang: function() { return _lang; },
		isReady: function() { return _ready; },

		onReady: function(fn) {
			if (_ready) fn();
			else _onReady.push(fn);
		},

		_fireReady: function() {
			this.translateDOM();
			for (var i = 0; i < _onReady.length; i++) _onReady[i]();
			_onReady = [];
		},

		// Translate DOM elements with data-i18n attribute
		translateDOM: function() {
			var els = document.querySelectorAll('[data-i18n]');
			for (var i = 0; i < els.length; i++) {
				var key = els[i].getAttribute('data-i18n');
				if (key) els[i].textContent = _t(key);
			}
		},

		// Available languages (add entries as translations are contributed)
		languages: {
			'en': 'English',
			'zh-TW': '繁體中文'
		}
	};

	window._t = _t;
	window.I18n = I18n;

})(window);
