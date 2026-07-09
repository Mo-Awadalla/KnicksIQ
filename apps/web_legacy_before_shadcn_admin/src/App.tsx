import { Link, NavLink, Route, Routes } from 'react-router-dom'
import Games from './pages/Games'
import GameDetail from './pages/GameDetail'
import PostgameReport from './pages/PostgameReport'
import SavedReports from './pages/SavedReports'
import Home from './pages/Home'
import AnalystChat from './pages/AnalystChat'

function App() {
  return (
    <div className="min-h-screen">
      <header className="bg-knicks-blue border-b-4 border-knicks-orange">
        <div className="container mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="text-2xl font-bold">
            <span className="text-white">Knicks</span>
            <span className="text-knicks-orange">IQ</span>
          </Link>
          <nav className="flex gap-6 text-sm">
            <NavLink
              to="/"
              className={({ isActive }) =>
                isActive ? 'text-knicks-orange font-semibold' : 'hover:text-knicks-orange'
              }
            >
              Home
            </NavLink>
            <NavLink
              to="/games"
              className={({ isActive }) =>
                isActive ? 'text-knicks-orange font-semibold' : 'hover:text-knicks-orange'
              }
            >
              Games
            </NavLink>
            <NavLink
              to="/reports"
              className={({ isActive }) =>
                isActive ? 'text-knicks-orange font-semibold' : 'hover:text-knicks-orange'
              }
            >
              Reports
            </NavLink>
            <NavLink
              to="/analyst"
              className={({ isActive }) =>
                isActive ? 'text-knicks-orange font-semibold' : 'hover:text-knicks-orange'
              }
            >
              Analyst
            </NavLink>
          </nav>
        </div>
      </header>

      <main className="container mx-auto px-6 py-8">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/games" element={<Games />} />
          <Route path="/games/:id" element={<GameDetail />} />
          <Route path="/reports/:id" element={<PostgameReport />} />
          <Route path="/reports" element={<SavedReports />} />
          <Route path="/analyst" element={<AnalystChat />} />
        </Routes>
      </main>

      <footer className="text-center text-knicks-silver text-xs py-6">
        KnicksIQ — built with FastAPI, RQ, MCP, and React.
      </footer>
    </div>
  )
}

export default App
