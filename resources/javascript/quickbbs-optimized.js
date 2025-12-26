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
        CACHE_DURATION: 300000, // 5 minutes
        LAZY_LOAD_TIMEOUT: 10000 // 10 seconds - force load all images after this delay
    };

    // Spinner Management with HTMX Content Replacement Handling
    class SpinnerManager {
        constructor() {
            this.spinnerTimeout = null;
            this.requestCount = 0;
        }

        getSpinner() {
            // Always check if spinner exists in DOM (HTMX may have removed it)
            let spinner = document.getElementById("spinner-overlay");
            if (!spinner) {
                spinner = this.createSpinner();
            }
            return spinner;
        }

        createSpinner() {
            // Remove any existing spinner first
            const existingSpinner = document.getElementById("spinner-overlay");
            if (existingSpinner) {
                existingSpinner.remove();
            }

            const spinner = document.createElement("div");
            spinner.id = "spinner-overlay";
            spinner.innerHTML = `
                <div id="spinner">
                    <div class="spinner-icon"></div>
                    <div>Loading...</div>
                </div>
            `;
            // Append to body, not to content that gets replaced
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
                const spinnerElement = document.getElementById("spinner-overlay");
                if (spinnerElement && this.requestCount === 0) {
                    spinnerElement.style.display = "none";
                }
            }, CONFIG.SPINNER_DELAY);
        }

        forceHide() {
            // Force hide spinner and reset state (for navigation events)
            this.requestCount = 0;
            clearTimeout(this.spinnerTimeout);
            const spinnerElement = document.getElementById("spinner-overlay");
            if (spinnerElement) {
                spinnerElement.style.display = "none";
            }
        }
    }

    // Lazy Loading Manager
    class LazyLoadManager {
        constructor() {
            this.observer = null;
            this.forceLoadTimeout = null;
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
                this.startForceLoadTimer();
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
            if (img.dataset.src && img.dataset.loaded !== 'true') {
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

        startForceLoadTimer() {
            // Clear any existing timer
            this.clearForceLoadTimer();

            // Set timeout to force load all remaining lazy images
            this.forceLoadTimeout = setTimeout(() => {
                const unloadedImages = document.querySelectorAll('img[data-src]');
                if (unloadedImages.length > 0) {
                    console.log(`Force loading ${unloadedImages.length} lazy images after timeout`);
                    this.loadAllImages();
                }
            }, CONFIG.LAZY_LOAD_TIMEOUT);
        }

        clearForceLoadTimer() {
            if (this.forceLoadTimeout) {
                clearTimeout(this.forceLoadTimeout);
                this.forceLoadTimeout = null;
            }
        }

        refresh() {
            if (this.observer) {
                this.observeImages();
                this.startForceLoadTimer();
            }
        }

        handleBFCache() {
            // Handle browser back/forward cache restoration
            const unloadedImages = document.querySelectorAll('img[data-loaded="false"][data-src]');
            if (unloadedImages.length > 0) {
                console.log(`BFCache restore: loading ${unloadedImages.length} lazy images`);
                unloadedImages.forEach(img => this.loadImage(img));
            }
        }

        cleanup() {
            this.clearForceLoadTimer();
        }
    }

    // Browser Native Lazy Loading Manager with Timeout
    class NativeLazyLoadManager {
        constructor() {
            this.timeouts = new Map();
            this.init();
        }

        init() {
            this.setupLazyImages();
        }

        setupLazyImages() {
            const lazyImages = document.querySelectorAll('img[loading="lazy"][data-lazy-timeout]');

            if (lazyImages.length === 0) return;

            console.log(`Found ${lazyImages.length} native lazy-loaded images with timeout`);

            lazyImages.forEach(img => {
                const timeout = parseInt(img.dataset.lazyTimeout) || 5000;

                // Clear existing timeout for this image if any
                if (this.timeouts.has(img)) {
                    clearTimeout(this.timeouts.get(img));
                }

                // Set a timeout to force load the image
                const timeoutId = setTimeout(() => {
                    // Check if image hasn't loaded yet (still has loading="lazy")
                    if (img.loading === 'lazy' && !img.complete) {
                        console.log('Auto-loading lazy image after timeout:', img.alt);
                        // Force load by setting loading to eager
                        img.loading = 'eager';
                    }
                    this.timeouts.delete(img);
                }, timeout);

                this.timeouts.set(img, timeoutId);
            });
        }

        cleanup() {
            // Clear all pending timeouts
            this.timeouts.forEach(timeoutId => clearTimeout(timeoutId));
            this.timeouts.clear();
        }

        refresh() {
            this.cleanup();
            this.setupLazyImages();
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
            this.nativeLazyLoader = new NativeLazyLoadManager();
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
            // HTMX Events - Handle both real requests and cached responses
            document.addEventListener("htmx:beforeRequest", (evt) => {
                evt.detail.requestConfig.startTime = this.performance.startRequest();
                this.spinner.show();
            });

            // Also show spinner on any HTMX trigger (including cached responses)
            document.addEventListener("htmx:trigger", (evt) => {
                this.spinner.show();
            });

            // Show spinner on any element with HTMX attribute clicked
            document.addEventListener("click", (evt) => {
                const target = evt.target.closest('[hx-get], [hx-post], [hx-put], [hx-delete], [hx-patch]');
                if (target) {
                    this.spinner.show();
                }
            });

            document.addEventListener("htmx:afterRequest", (evt) => {
                if (evt.detail.requestConfig.startTime) {
                    this.performance.endRequest(evt.detail.requestConfig.startTime);
                }
                this.spinner.hide();
            });

            document.addEventListener("htmx:afterSettle", () => {
                this.spinner.hide();
                this.lazyLoader.refresh();
                this.nativeLazyLoader.refresh();
            });

            document.addEventListener("htmx:beforeSwap", () => {
                // Clean up timers before content swap
                this.lazyLoader.cleanup();
                this.nativeLazyLoader.cleanup();
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

            // Browser navigation events (back/forward button)
            window.addEventListener("pageshow", (evt) => {
                this.spinner.forceHide();
                // If page was restored from bfcache, reload lazy images
                if (evt.persisted) {
                    this.lazyLoader.handleBFCache();
                }
            });

            window.addEventListener("pagehide", () => {
                this.spinner.forceHide();
            });

            // HTMX history events
            document.addEventListener("htmx:historyRestore", () => {
                this.spinner.forceHide();
                // Reload lazy images when HTMX restores from history
                this.lazyLoader.handleBFCache();
            });

            // Additional safety net - check for stuck spinners periodically
            setInterval(() => {
                const spinnerElement = document.getElementById("spinner-overlay");
                if (spinnerElement && spinnerElement.style.display === "flex" && this.spinner.requestCount === 0) {
                    this.spinner.forceHide();
                }
            }, 5000); // Check every 5 seconds

            // Error handling
            document.addEventListener("htmx:responseError", (evt) => {
                console.error('HTMX Response Error:', evt.detail);
                this.spinner.hide();
                this.showErrorModal(evt.detail);
            });

            document.addEventListener("htmx:timeout", (evt) => {
                console.warn('HTMX Request Timeout:', evt.detail);
                this.spinner.hide();
                this.showErrorModal({
                    error: 'Request Timeout',
                    statusCode: 408
                });
            });

            document.addEventListener("htmx:sendError", (evt) => {
                console.error('HTMX Network Error:', evt.detail);
                this.spinner.hide();
                this.showErrorModal({
                    error: 'Network Error - Unable to connect to server',
                    statusCode: 0
                });
            });

            // Error modal event listeners
            document.addEventListener('DOMContentLoaded', () => {
                const modal = document.getElementById('error-modal');
                if (modal) {
                    const modalBackground = modal.querySelector('.modal-background');
                    const modalClose = modal.querySelector('.modal-close');

                    if (modalBackground) {
                        modalBackground.addEventListener('click', () => this.hideErrorModal());
                    }

                    if (modalClose) {
                        modalClose.addEventListener('click', () => this.hideErrorModal());
                    }
                }
            });

            // Close modal on ESC key
            document.addEventListener('keydown', (evt) => {
                if (evt.key === 'Escape') {
                    this.hideErrorModal();
                }
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

        showErrorModal(detail) {
            const modal = document.getElementById('error-modal');
            const content = document.getElementById('error-message-content');

            if (!modal || !content) {
                console.error('Error modal elements not found');
                return;
            }

            let message = 'An unexpected error occurred.';

            if (detail.xhr) {
                const status = detail.xhr.status;
                const statusText = detail.xhr.statusText || 'Unknown Error';
                message = `Server Error (${status}): ${statusText}`;

                // Try to get more details from response
                try {
                    const responseText = detail.xhr.responseText;
                    if (responseText && responseText.length < 200) {
                        message += `\n\n${responseText}`;
                    }
                } catch (e) {
                    // Ignore if we can't get response text
                }
            } else if (detail.error) {
                message = detail.error;
            } else if (detail.statusCode) {
                message = `Error ${detail.statusCode}: ${detail.error || 'Request failed'}`;
            }

            content.textContent = message;
            modal.classList.add('is-active');
            document.documentElement.classList.add('is-clipped');
        }

        hideErrorModal() {
            const modal = document.getElementById('error-modal');
            if (modal) {
                modal.classList.remove('is-active');
                document.documentElement.classList.remove('is-clipped');
            }
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