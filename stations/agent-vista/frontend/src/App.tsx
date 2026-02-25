// Root component — PixelOffice canvas + Dashboard overlay

import { useEffect } from 'react';
import PixelOffice from './components/PixelOffice';
import Dashboard from './components/Dashboard';
import ChatChannel from './components/ChatChannel';
import AgentDetailPanel from './components/AgentDetailPanel';
import { useWSStore } from './stores/wsStore';
import { useOfficeStore } from './stores/officeStore';
import { useResourceStore } from './stores/resourceStore';
import { useWatchdogStore } from './stores/watchdogStore';
import { useSoundEffects } from './hooks/useSoundEffects';

export default function App() {
  const connect = useWSStore(s => s.connect);
  const startMock = useWSStore(s => s.startMock);
  const loadLayout = useOfficeStore(s => s.loadLayout);
  const startResourcePolling = useResourceStore(s => s.startPolling);
  const startWatchdog = useWatchdogStore(s => s.startWatching);

  useSoundEffects();

  useEffect(() => {
    // Try to load saved layout from backend
    loadLayout().then(loaded => {
      if (loaded) console.log('[agent-vista] Layout loaded from database');
    });

    // Fall back to mock only if connect truly failed (not still connecting)
    const timeout = setTimeout(() => {
      const { status } = useWSStore.getState();
      if (status === 'disconnected') {
        console.log('[agent-vista] Backend unavailable, starting mock mode');
        startMock();
      }
    }, 4000);

    connect();
    startResourcePolling();
    startWatchdog();

    return () => clearTimeout(timeout);
  }, [connect, startMock]);

  return (
    <>
      <PixelOffice />
      <Dashboard />
      <ChatChannel />
      <AgentDetailPanel />
    </>
  );
}
