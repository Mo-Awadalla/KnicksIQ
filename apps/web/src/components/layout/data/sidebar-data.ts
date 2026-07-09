import {
  Activity,
  BarChart3,
  Bot,
  CalendarDays,
  ClipboardList,
  LayoutDashboard,
  RadioTower,
} from 'lucide-react'
import { type SidebarData } from '../types'

export const sidebarData: SidebarData = {
  user: {
    name: 'KnicksIQ',
    email: 'sports-ops@knicksiq.local',
    avatar: '/avatars/shadcn.jpg',
  },
  teams: [
    {
      name: 'KnicksIQ',
      logo: Activity,
      plan: 'Sports Ops',
    },
  ],
  navGroups: [
    {
      title: 'Command Center',
      items: [
        {
          title: 'Games Command',
          url: '/',
          icon: LayoutDashboard,
        },
        {
          title: 'Games',
          url: '/games',
          icon: CalendarDays,
        },
        {
          title: 'Reports',
          url: '/reports',
          icon: ClipboardList,
        },
        {
          title: 'Analyst',
          url: '/analyst',
          icon: Bot,
        },
      ],
    },
    {
      title: 'Operations',
      items: [
        {
          title: 'Data Pipeline',
          url: '/games',
          badge: 'Admin',
          icon: RadioTower,
        },
        {
          title: 'Analysis Outputs',
          url: '/reports',
          icon: BarChart3,
        },
      ],
    },
  ],
}
