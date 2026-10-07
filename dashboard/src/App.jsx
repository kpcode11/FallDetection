import React, { useState, useEffect } from 'react';
import mqtt from 'mqtt';
import { Activity, AlertTriangle, ShieldCheck, Database } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

const MQTT_BROKER = "wss://broker.hivemq.com:8884/mqtt";
const TOPIC_ALERT = "ioe-lab/fall-detection/team41/alert";
const TOPIC_DATA = "ioe-lab/fall-detection/team41/sensor_data";

function NavBar({ connected }) {
  return (
    <nav className="nav-bar-light">
      <div className="flex items-center gap-4">
        <div style={{ backgroundColor: 'var(--primary)', padding: '6px', borderRadius: 'var(--rounded-md)' }}>
          <Activity color="var(--on-primary)" size={20} />
        </div>
        <span className="heading-md" style={{ fontWeight: 600 }}>Fall Detection</span>
        <span className="pill-tag-soft ml-4">v1.0.0</span>
      </div>
      <div className="flex items-center gap-2">
        <span className={`status-dot ${connected ? 'connected' : 'disconnected'}`}></span>
        <span className="micro" style={{ color: 'var(--ink-mute)' }}>
          {connected ? 'Connected to HiveMQ' : 'Disconnected'}
        </span>
      </div>
    </nav>
  );
}

function SensorGraph({ rawWindow }) {
  if (!rawWindow || rawWindow.length === 0) {
    return (
      <div className="card-feature-dark flex items-center" style={{ justifyContent: 'center', minHeight: '300px' }}>
        <p className="body-md" style={{ color: 'var(--ink-mute-2)' }}>Waiting for sensor data stream...</p>
      </div>
    );
  }

  const data = rawWindow.map((sample, i) => ({
    time: i,
    x: sample[0],
    y: sample[1],
    z: sample[2],
    magnitude: Math.sqrt(sample[0]**2 + sample[1]**2 + sample[2]**2).toFixed(2)
  }));

  return (
    <div className="card-feature-dark">
      <div className="flex justify-between items-center mb-4">
        <h3 className="heading-md flex items-center gap-2">
          <Database size={18} color="var(--primary)" />
          Live 30-Sample Window (10Hz)
        </h3>
        <span className="micro" style={{ color: 'var(--primary-soft)' }}>Live Feed Active</span>
      </div>
      <div style={{ height: 250 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#333" />
            <XAxis dataKey="time" stroke="#707070" tick={{fontSize: 12}} />
            <YAxis stroke="#707070" tick={{fontSize: 12}} domain={[0, 'auto']} />
            <Tooltip contentStyle={{ backgroundColor: '#1c1c1c', border: '1px solid #333' }} />
            <Line type="monotone" dataKey="magnitude" stroke="var(--primary)" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="x" stroke="#707070" strokeWidth={1} dot={false} />
            <Line type="monotone" dataKey="y" stroke="#9a9a9a" strokeWidth={1} dot={false} />
            <Line type="monotone" dataKey="z" stroke="#dfdfdf" strokeWidth={1} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function AlertFeed({ alerts }) {
  return (
    <div className="card-feature-light" style={{ marginTop: '32px' }}>
      <h2 className="display-md mb-6">Confirmed Alerts</h2>
      
      {alerts.length === 0 ? (
        <div style={{ padding: '48px 0', textAlign: 'center' }}>
          <ShieldCheck size={48} color="var(--primary)" style={{ margin: '0 auto 16px' }} />
          <p className="body-md">System is monitoring. No falls detected.</p>
        </div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>TIME</th>
              <th>DEVICE ID</th>
              <th>EVENT TYPE</th>
              <th>REASON</th>
              <th>STATUS</th>
            </tr>
          </thead>
          <tbody>
            {alerts.map((alert, i) => (
              <tr key={i}>
                <td>{alert.time}</td>
                <td style={{ fontFamily: 'var(--typography-code)' }}>{alert.device}</td>
                <td>
                  <span className="pill-tag-green" style={{ backgroundColor: '#ff2201' }}>
                    <AlertTriangle size={10} style={{ display: 'inline', marginRight: '4px', marginBottom: '-1px' }}/>
                    {alert.event}
                  </span>
                </td>
                <td style={{ color: 'var(--ink-mute)' }}>{alert.reason}</td>
                <td>Received</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function App() {
  const [connected, setConnected] = useState(false);
  const [alerts, setAlerts] = useState([]);
  const [lastWindow, setLastWindow] = useState([]);

  useEffect(() => {
    console.log("Connecting to MQTT...");
    const client = mqtt.connect(MQTT_BROKER);

    client.on('connect', () => {
      setConnected(true);
      client.subscribe(TOPIC_ALERT);
      client.subscribe(TOPIC_DATA);
    });

    client.on('message', (topic, message) => {
      try {
        const payload = JSON.parse(message.toString());
        
        if (topic === TOPIC_ALERT) {
          const newAlert = {
            time: new Date().toLocaleTimeString(),
            device: payload.device || "unknown",
            event: payload.event || "ALERT",
            reason: payload.reason || "Fall detected"
          };
          setAlerts(prev => [newAlert, ...prev].slice(0, 10)); // Keep last 10
        } 
        else if (topic === TOPIC_DATA) {
          if (payload.window) {
            setLastWindow(payload.window);
          }
        }
      } catch (e) {
        console.error("Failed to parse MQTT message", e);
      }
    });

    return () => client.end();
  }, []);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <NavBar connected={connected} />
      
      <main className="container" style={{ flex: 1, width: '100%' }}>
        <div className="flex justify-between items-center mb-8">
          <div>
            <h1 className="display-xl mb-2">Live Monitoring</h1>
            <p className="body-lg" style={{ color: 'var(--ink-mute)' }}>
              Real-time visualization of sensor streams and Tier-2 AI classifications.
            </p>
          </div>
        </div>

        {/* Composited UI Stack */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
          <SensorGraph rawWindow={lastWindow} />
          <AlertFeed alerts={alerts} />
        </div>
      </main>

      <footer className="footer-light text-center" style={{ backgroundColor: 'var(--canvas)', padding: '48px', color: 'var(--ink-mute-2)' }}>
        <p className="caption">Powered by Supabase-inspired Design Language • Built for Fall Detection v1.0</p>
      </footer>
    </div>
  );
}

export default App;
