// Deployment-time configuration. Keep both values empty for offline demo mode.
// Example: window.ROBOT_DIAGNOSTIC_API = 'http://127.0.0.1:8080/api/v1';
// Development shortcut: append ?api=http://127.0.0.1:8000/api/v1 to the page URL.
var robotApiFromQuery = new URLSearchParams(window.location.search).get('api') || '';
window.ROBOT_DIAGNOSTIC_API = window.ROBOT_DIAGNOSTIC_API || robotApiFromQuery;
window.ROBOT_DATA_ADAPTER = window.ROBOT_DATA_ADAPTER || null;
