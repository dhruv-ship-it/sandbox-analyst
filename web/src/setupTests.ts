// Tells React's `act()` that this jsdom environment is a test environment,
// silencing an otherwise-spurious warning on every act() call.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
