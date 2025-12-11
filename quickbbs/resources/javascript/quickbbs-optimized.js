/**
 * QuickBBS Custom JavaScript
 *
 * This file contains custom JavaScript functionality for the QuickBBS application.
 */

/**
 * Clear HTMX cache when show_duplicates preference changes
 *
 * When the user toggles the "show duplicates" preference, the server sends
 * an HX-Trigger header with the event name "clearPreferenceCache". This
 * listener catches that event and forces a reload of the current page to
 * ensure the updated preference is reflected immediately.
 *
 * This prevents the browser from serving stale cached HTML with the old
 * preference value when navigating back to previously viewed pages.
 */
document.addEventListener('clearPreferenceCache', function(event) {
    if (typeof htmx !== 'undefined') {
        // Force reload of current page with updated preference
        // This bypasses the browser cache and ensures fresh content
        htmx.ajax('GET', window.location.href, {
            target: 'body',
            swap: 'outerHTML'
        });
    }
});
