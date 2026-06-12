import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

// StrictMode removed — it double-invokes effects which causes issues with WebGL/Live2D
createRoot(document.getElementById('root')).render(<App />)

