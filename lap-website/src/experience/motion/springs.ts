export const physics = {
  scrollLerp: 0.08,
  scrollDuration: 1.2,
  scrollSnapForce: 0.4,
  magnetismRadius: 120,
  magnetismStrength: 0.15,
  magnetismDecay: 2.0,
  dragFriction: 0.92,
  dragOvershoot: 0.04,
  velocitySmoothing: 0.12,
  velocityMax: 1.0,
  snapVelocityThreshold: 0.05,
} as const;

export const reveal = {
  brushRadius: 80,
  brushSoftness: 0.6,
  decayFactor: 0.985,
  blurKernelSize: 5,
  blurSigma: 2.0,
  inertiaLerp: 0.08,
  turbulenceStrength: 0.3,
  turbulenceScale: 4.0,
  drsRadiusMultiplier: 1.4,
  idleDecayRate: 0.97,
  idleTimeout: 2000,
  mobileBurstRadius: 120,
  mobileBurstDecay: 0.96,
} as const;

export const background = {
  grainIntensity: 0.04,
  contourCount: 30,
  contourDriftSpeed: 0.001,
  contourPointerInfluence: 0.03,
  particleDriftX: 2.0,
  particleDriftY: 2.0,
  particlePointerRadius: 100,
  streakCount: 15,
  streakSpawnThreshold: 0.4,
  streakLifetime: 300,
  streakLength: 40,
  vignetteRadius: 0.7,
  vignetteShift: 0.05,
  yawDamping: 0.04,
  cornerParallaxFactor: 0.02,
  wheelFriction: 0.95,

  // New: Track ribbon
  ribbonWidth: 8,                  // world units
  ribbonEdgeEmissive: 0.08,        // edge glow opacity
  ribbonSegmentGlow: 0.12,         // completed sector glow opacity
  ribbonForwardGlow: 0.20,         // brighter emission ahead of camera
  ribbonStepSize: 0.5,             // world units per ribbon segment

  // New: Corner feel
  cornerYawRange: 3.0,             // max degrees (±3°)
  cornerBankRange: 1.5,            // max degrees (±1.5°)
  cornerLerp: 0.05,               // per-frame lerp toward target yaw/bank
  cornerParticleDriftMultiplier: 2.0, // lateral drift amplifier in corners

  // New: Streak DRS modulation
  streakDrsThresholdReduction: 0.4, // spawn threshold × (1 - this) during DRS

  // Studio light sweep
  lightSweepSpeed: 0.3,             // radians/second base rate

  // Pointer distortion (postprocessing)
  pointerDistortionRadius: 0.15,    // normalized viewport units
  pointerDistortionStrength: 0.003, // max pixel displacement (barrel)

  // Metallic event flash durations (ms)
  metallicFlashDuration: {
    sector: 600,
    drs: 900,
    finish: 400,
    guidance: 250,
  },
} as const;
