// Deployment-time configuration. When served by the unified backend, use that
// same origin automatically. Vite development remains demo mode unless ?api=
// is supplied, for example ?api=http://127.0.0.1:8000/api/v1.
var robotApiFromQuery = new URLSearchParams(window.location.search).get('api') || '';
var robotApiFromUnifiedService = !['5173', '5174'].includes(window.location.port)
  ? window.location.origin + '/api/v1'
  : '';
window.ROBOT_DIAGNOSTIC_API = window.ROBOT_DIAGNOSTIC_API || robotApiFromQuery || robotApiFromUnifiedService;
window.ROBOT_DATA_ADAPTER = window.ROBOT_DATA_ADAPTER || null;
