import { Analytics } from '@vercel/analytics/react';
import HeroSection from './components/HeroSection';
import { BrowserShell } from './components/BrowserShell';
import ClickSpark from './components/ClickSpark';

function App() {
  return (
    <ClickSpark
      sparkColor={['#ff99cc', '#a855f7', '#2563eb']}
      sparkSize={12}
      sparkRadius={20}
      sparkCount={10}
      duration={400}
    >
      <HeroSection />
      <BrowserShell />
      <Analytics />
    </ClickSpark>
  );
}

export default App;
