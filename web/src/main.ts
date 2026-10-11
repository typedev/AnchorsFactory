// The web Studio: the local Studio's page and script, talking to Python in a
// worker instead of the HTTP server. The transport must exist before app.js
// runs (it starts at once), so it is imported first.
import './transport'
import '../../anchorsfactory/studio/static/app.css'
import '../../anchorsfactory/studio/static/app.js'
