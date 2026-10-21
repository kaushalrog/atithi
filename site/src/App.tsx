import { LazyMotion, MotionConfig, domAnimation } from "motion/react";
import { Hero } from "./components/Hero";
import { Nav } from "./components/Nav";
import { SampleBooking } from "./components/SampleBooking";
import { Capabilities, Closing, Footer, HowItWorks, Product, Trust, UseCases } from "./components/Sections";

export default function App() {
  return (
    // LazyMotion + `m` keeps Motion's bundle to the DOM animation features we use.
    // reducedMotion="user" makes every Motion animation honour the OS setting.
    <LazyMotion features={domAnimation} strict>
      <MotionConfig reducedMotion="user">
        <a className="skip" href="#main">Skip to content</a>
        <Nav />
        <main id="main">
          <Hero />
          <SampleBooking />
          <Capabilities />
          <Product />
          <UseCases />
          <HowItWorks />
          <Trust />
          <Closing />
        </main>
        <Footer />
      </MotionConfig>
    </LazyMotion>
  );
}
