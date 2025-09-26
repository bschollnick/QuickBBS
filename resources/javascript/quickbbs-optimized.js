/**
 * QuickBBS Optimized JavaScript
 * Consolidated spinner management, HTMX optimizations, and performance enhancements
 */

(function() {
    'use strict';

    // Configuration
    const CONFIG = {
        SPINNER_DELAY: 100,
        LAZY_LOAD_THRESHOLD: '10px',
        CACHE_DURATION: 300000 // 5 minutes
    };

    // Spinner Management with Performance Optimizations
    class SpinnerManager {
        constructor() {
            this.spinnerTimeout = null;
            this.spinner = null;
            this.requestCount = 0;
        }

        getSpinner() {
            if (!this.spinner) {
                this.spinner = document.getElementById("spinner-overlay");
                if (!this.spinner) {
                    this.spinner = this.createSpinner();
                }
            }
            return this.spinner;
        }

        createSpinner() {
            const spinner = document.createElement("div");
            spinner.id = "spinner-overlay";
            spinner.innerHTML = `
                <div id="spinner">
                    <div class="spinner-icon"></div>
                    <div>Loading...</div>
                </div>
            `;
            document.body.appendChild(spinner);
            return spinner;
        }

        show() {
            this.requestCount++;
            clearTimeout(this.spinnerTimeout);
            const spinnerElement = this.getSpinner();
            if (spinnerElement) {
                spinnerElement.style.display = "flex";
            }
        }

        hide() {
            this.requestCount = Math.max(0, this.requestCount - 1);
            if (this.requestCount > 0) return;

            clearTimeout(this.spinnerTimeout);
            this.spinnerTimeout = setTimeout(() => {
                const spinnerElement = this.getSpinner();
                if (spinnerElement && this.requestCount === 0) {
                    spinnerElement.style.display = "none";
                }
            }, CONFIG.SPINNER_DELAY);
        }
    }

    // Lazy Loading Manager
    class LazyLoadManager {
        constructor() {
            this.observer = null;
            this.init();
        }

        init() {
            if ('IntersectionObserver' in window) {
                this.observer = new IntersectionObserver(
                    this.handleIntersection.bind(this),
                    {
                        rootMargin: CONFIG.LAZY_LOAD_THRESHOLD,
                        threshold: 0.1
                    }
                );
                this.observeImages();
            } else {
                // Fallback for older browsers
                this.loadAllImages();
            }
        }

        handleIntersection(entries) {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    this.loadImage(img);
                    this.observer.unobserve(img);
                }
            });
        }

        loadImage(img) {
            if (img.dataset.src) {
                img.src = img.dataset.src;
                img.dataset.loaded = 'true';
                img.removeAttribute('data-src');
            }
        }

        loadAllImages() {
            document.querySelectorAll('img[data-src]').forEach(img => {
                this.loadImage(img);
            });
        }

        observeImages() {
            document.querySelectorAll('img[data-src]').forEach(img => {
                this.observer.observe(img);
            });
        }

        refresh() {
            if (this.observer) {
                this.observeImages();
            }
        }
    }

    // Cache Manager for HTMX Requests
    class CacheManager {
        constructor() {
            this.cache = new Map();
        }

        get(key) {
            const entry = this.cache.get(key);
            if (entry && Date.now() - entry.timestamp < CONFIG.CACHE_DURATION) {
                return entry.data;
            }
            this.cache.delete(key);
            return null;
        }

        set(key, data) {
            this.cache.set(key, {
                data: data,
                timestamp: Date.now()
            });
        }

        clear() {
            this.cache.clear();
        }
    }

    // Performance Monitor
    class PerformanceMonitor {
        constructor() {
            this.metrics = {
                requestCount: 0,
                totalRequestTime: 0,
                averageRequestTime: 0
            };
        }

        startRequest() {
            return performance.now();
        }

        endRequest(startTime) {
            const duration = performance.now() - startTime;
            this.metrics.requestCount++;
            this.metrics.totalRequestTime += duration;
            this.metrics.averageRequestTime = this.metrics.totalRequestTime / this.metrics.requestCount;

            // Log slow requests
            if (duration > 1000) {
                console.warn(`Slow HTMX request detected: ${duration}ms`);
            }
        }

        getMetrics() {
            return { ...this.metrics };
        }
    }

    // Main Application
    class QuickBBSApp {
        constructor() {
            this.spinner = new SpinnerManager();
            this.lazyLoader = new LazyLoadManager();
            this.cache = new CacheManager();
            this.performance = new PerformanceMonitor();
            this.init();
        }

        init() {
            this.setupEventListeners();
            this.setupHTMXOptimizations();
            this.setupTitleUpdates();
        }

        setupEventListeners() {
            // HTMX Events
            document.addEventListener("htmx:beforeRequest", (evt) => {
                evt.detail.requestConfig.startTime = this.performance.startRequest();
                this.spinner.show();
            });

            document.addEventListener("htmx:afterRequest", (evt) => {
                this.performance.endRequest(evt.detail.requestConfig.startTime);
                this.spinner.hide();
            });

            document.addEventListener("htmx:afterSettle", () => {
                this.spinner.hide();
                this.lazyLoader.refresh();
            });

            // Regular link clicks (non-HTMX)
            document.addEventListener("click", (evt) => {
                const target = evt.target.closest('a');
                if (target && target.href && !this.isHTMXElement(target)) {
                    if (target.target !== '_blank' && target.target !== '_new') {
                        this.spinner.show();
                    }
                }
            });

            // Cleanup events
            window.addEventListener("load", () => this.spinner.hide());
            document.addEventListener("visibilitychange", () => {
                if (document.visibilityState === 'visible') {
                    this.spinner.hide();
                }
            });

            // Error handling
            document.addEventListener("htmx:responseError", (evt) => {
                console.error('HTMX Response Error:', evt.detail);
                this.spinner.hide();
            });

            document.addEventListener("htmx:timeout", (evt) => {
                console.warn('HTMX Request Timeout:', evt.detail);
                this.spinner.hide();
            });
        }

        setupHTMXOptimizations() {
            // Add request headers for optimization
            document.addEventListener("htmx:configRequest", (evt) => {
                evt.detail.headers['X-Requested-With'] = 'HTMX';
                evt.detail.headers['Cache-Control'] = 'max-age=300';
            });

            // Optimize swap strategies
            document.addEventListener("htmx:beforeSwap", (evt) => {
                // Add fade transition for better UX
                if (evt.detail.target) {
                    evt.detail.target.style.transition = 'opacity 0.2s ease-in-out';
                }
            });
        }

        setupTitleUpdates() {
            // Enhanced title update logic for HTMX requests
            document.addEventListener("htmx:afterSettle", (evt) => {
                const titleScript = evt.detail.target.querySelector('script[data-title-update]');
                if (titleScript) {
                    try {
                        eval(titleScript.textContent);
                    } catch (e) {
                        console.warn('Title update script error:', e);
                    }
                }
            });
        }

        isHTMXElement(element) {
            return element.hasAttribute('hx-get') ||
                   element.hasAttribute('hx-post') ||
                   element.hasAttribute('hx-put') ||
                   element.hasAttribute('hx-delete') ||
                   element.hasAttribute('hx-patch');
        }

        updateFiletypeColor(color) {
            document.documentElement.style.setProperty('--filetype-color', `#${color}`);
        }

        // Public API
        getPerformanceMetrics() {
            return this.performance.getMetrics();
        }

        clearCache() {
            this.cache.clear();
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.QuickBBS = new QuickBBSApp();
        });
    } else {
        window.QuickBBS = new QuickBBSApp();
    }

    // Expose utilities globally for templates
    window.QuickBBSUtils = {
        updateFiletypeColor: (color) => {
            if (window.QuickBBS) {
                window.QuickBBS.updateFiletypeColor(color);
            }
        },
        getMetrics: () => {
            return window.QuickBBS ? window.QuickBBS.getPerformanceMetrics() : {};
        }
    };

})();