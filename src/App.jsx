import HeroSection from './components/HeroSection';
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
    </ClickSpark>
  );
}

export default App;
