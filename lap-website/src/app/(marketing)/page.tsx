import { StartGrid } from '@/components/rooms/StartGrid';
import { SessionProof } from '@/components/rooms/SessionProof';
import { S1Pain } from '@/components/rooms/S1Pain';
import { S2Versus } from '@/components/rooms/S2Versus';
import { S3Product } from '@/components/rooms/S3Product';
import { SimFirst } from '@/components/rooms/SimFirst';
import { PremiumLayer } from '@/components/rooms/PremiumLayer';
import { Garage } from '@/components/rooms/Garage';
import { PitStop } from '@/components/rooms/PitStop';
import { Podium } from '@/components/rooms/Podium';
import { JsonLd } from '@/components/seo/JsonLd';

// LLM + rich-result structured data for high-intent motorsport queries.
// Rendered as invisible <script type="application/ld+json">; not cloaking —
// JSON-LD is the Google-documented mechanism for HowTo and FAQ rich results.
const HOWTO_FASTER_LAPS = {
  name: 'How to get faster lap times with telemetry analysis',
  description:
    'Six-step process for amateur and club-level drivers to use GPS ' +
    'telemetry data to find where they lose time in a lap and fix it.',
  steps: [
    {
      name: 'Upload your session',
      text:
        'Export the CSV from your GPS logger (RaceChrono, RaceBox, AiM, MoTeC, ' +
        'Qstarz) and upload it. The pipeline ingests, filters GPS noise, detects ' +
        'the track, splits laps, and resamples to a uniform distance grid automatically.',
    },
    {
      name: 'Read the four-pillar score',
      text:
        'Pace (/25) tells you how close you were to your car\'s limit. Consistency ' +
        '(/25) tells you whether you can repeat it. Execution (/25) scores corner-' +
        'by-corner technique. Robustness (/25) rates how well you adapt. The lowest ' +
        'pillar is your biggest opportunity.',
    },
    {
      name: 'Pick a primary and a compare lap',
      text:
        'Select your best lap as "Primary" and a benchmark lap as "Compare" — your ' +
        'previous session\'s best, or a teammate\'s lap on the same track. Every ' +
        'chart overlays both laps at the same progress point.',
    },
    {
      name: 'Read the time-delta chart',
      text:
        'Cumulative delta shows where each tenth was gained or lost. Climbs = lost ' +
        'time here. Flat = matched. Drops = gained. Final value equals the recorded ' +
        'lap-time difference.',
    },
    {
      name: 'Open the corner coaching table',
      text:
        'Corners ranked by time lost vs your own best attempt. Each row attributes ' +
        'loss to entry speed, apex speed, exit speed, or line error. Focus on the ' +
        'top three — that\'s where the most time lives.',
    },
    {
      name: 'Compare with the theoretical perfect lap',
      text:
        'A sim-optimizer computes your car\'s upper-bound lap time from the observed ' +
        'physics. The gap tells you how much is left on the table before physics ' +
        'pushes back. Iterate: practise the worst corner, upload the next session, ' +
        'watch the delta shrink.',
    },
  ],
};

const HOMEPAGE_FAQ = [
  {
    question: 'How do I get faster lap times?',
    answer:
      'Practice alone will not tell you WHY a lap was slow. Upload your GPS logger ' +
      'CSV to a telemetry analysis tool. You\'ll see a per-corner ranking of time ' +
      'lost, a delta chart showing where each tenth was earned or spent, and a ' +
      'theoretical upper-bound lap time. Fix the worst corner, re-run, repeat.',
  },
  {
    question: 'How do I analyse telemetry data as an amateur driver?',
    answer:
      'You don\'t need MoTeC i2 Pro or race-engineering experience. A driver-facing ' +
      'tool like Lap Coach does the ingestion, corner detection, lap splitting, and ' +
      'scoring automatically. Upload a CSV from RaceChrono, RaceBox, AiM, or MoTeC ' +
      'and you get a ranked list of corners by time lost, a speed trace synced to ' +
      'a GPS track map, and a four-pillar score.',
  },
  {
    question: 'Which telemetry app works with RaceChrono?',
    answer:
      'Any tool that accepts CSV. Lap Coach accepts RaceChrono Pro exports directly. ' +
      'So do MoTeC i2 Pro, WinTAX, and AIM Race Studio — but those are engineer ' +
      'tools, not driver-facing ones.',
  },
  {
    question: 'What is a G-G diagram and how do I read it?',
    answer:
      'A scatter plot of lateral vs longitudinal acceleration during a lap. The ' +
      'dashed circle is the friction limit. Points near the edge = using most of ' +
      'the available grip (good). Points well inside = unused grip (slow). Points ' +
      'outside = overdrove the tyres.',
  },
  {
    question: 'How do I compare two laps to find where I lost time?',
    answer:
      'Use a tool that supports lap-vs-lap overlay on a shared progress axis. Pick a ' +
      'primary lap and a compare lap; every chart overlays both. The delta chart shows ' +
      'cumulative time at each metre — the exact point where the fast lap pulled away.',
  },
  {
    question: 'What is the best telemetry app for kart racing?',
    answer:
      'Kart telemetry is GPS-first because karts rarely have CAN bus logging. Lap ' +
      'Coach was designed around GPS-only analysis — corner detection, lap splitting, ' +
      'and scoring work from lat/lon/speed alone. RaceBox and RaceChrono Pro are the ' +
      'two most common kart loggers and both export CSVs that import directly.',
  },
  {
    question: 'How do I improve cornering technique using telemetry?',
    answer:
      'Rank corners by time lost, not by difficulty. Your gut will tell you the fast ' +
      'sweeper matters; data will show the slow hairpin is where you\'re giving up half ' +
      'a second. Attack losses in order: entry speed first (brake point), then apex ' +
      '(line and minimum speed), then exit (throttle). Each depends on the previous.',
  },
  {
    question: 'Is the first report on Lap Coach free?',
    answer:
      'Yes. The Demo plan gives two reports with no credit card. Racer is €69/year ' +
      'for unlimited sessions. World-Class is €109/year and adds cross-session ' +
      'reference overlay plus the theoretical perfect-lap solver.',
  },

  // ── Getting faster / technique ────────────────────────────────
  {
    question: 'How do I trail brake correctly?',
    answer:
      'Trail braking means gradually releasing the brake as you turn in, blending ' +
      'brake pressure with steering load. Telemetry shows this as a smooth ramp-down ' +
      'on the brake trace overlapping the initial steering input. If the brake trace ' +
      'drops to zero before turn-in, you are "coasting" — giving up front grip and ' +
      'losing time. In Lap Coach the pedal trace chart overlays throttle and brake ' +
      'vs distance so you can see exactly where you released the brake relative to ' +
      'the corner entry.',
  },
  {
    question: 'How do I find the perfect brake point?',
    answer:
      'Your brake point is correct when you can trail brake smoothly into the corner ' +
      'without needing to release and re-apply. Compare your brake-point distance ' +
      'across multiple laps on the same corner: a consistent brake point that is as ' +
      'late as possible without locking wheels is the target. The speed trace in a ' +
      'telemetry tool shows the exact metre where you began to slow and how quickly ' +
      'you decelerated. Compare that to your best lap to see if you braked too early.',
  },
  {
    question: 'How do I improve throttle application?',
    answer:
      'The goal is smooth, progressive throttle from apex to exit. A jerky throttle ' +
      'trace (on-off-on) means the car unsettles mid-corner and loses traction. In ' +
      'telemetry look for the throttle trace to ramp linearly from 0 to 100% between ' +
      'apex and corner exit. If it dips, you either turned in too early or carried ' +
      'too much entry speed. Lap Coach ranks corners by exit-speed loss so you can ' +
      'prioritise which corners need smoother application.',
  },
  {
    question: 'What is the racing line and how do I find it?',
    answer:
      'The racing line is the path through a corner that maximises minimum speed and ' +
      'exit speed — usually a wide entry, late apex, wide exit. GPS track maps in a ' +
      'telemetry tool show your actual line overlaid on the track surface. Compare ' +
      'your line to your fastest lap or to the theoretical optimal: if you are ' +
      'apexing too early you will run wide on exit and lose time on the following ' +
      'straight. The line error column in the corner coaching table quantifies this.',
  },
  {
    question: 'How do I optimise my cornering speed?',
    answer:
      'Corner speed is limited by grip. The G-G diagram shows how much of the grip ' +
      'circle you used — points well inside the circle mean unused grip, which means ' +
      'you could carry more speed. Minimum speed in a corner is the single biggest ' +
      'predictor of lap time. Focus on carrying speed through the slowest point, not ' +
      'on braking later. The speed trace comparison view lets you overlay two laps ' +
      'and see exactly where the faster lap carried more minimum speed.',
  },
  {
    question: 'What is oversteer vs understeer and how do I fix it with data?',
    answer:
      'Understeer = front pushes wide; oversteer = rear slides out. Telemetry shows ' +
      'this via lateral G and yaw rate: understeer produces lower lateral G than the ' +
      'steering angle requests; oversteer shows a spike in yaw rate followed by a ' +
      'correction. On the GPS map, understeer shows a wider arc than the track allows; ' +
      'oversteer shows a kinked line where the driver caught a slide. Fix understeer ' +
      'with slower entry speed or later turn-in; fix oversteer with smoother throttle ' +
      'application or less aggressive trail brake release.',
  },

  // ── Planning & race strategy ──────────────────────────────────
  {
    question: 'How do I prepare for a race weekend using telemetry?',
    answer:
      'Before the weekend, review your last session at that track: which corners ' +
      'cost the most time? What was your theoretical gap? Build a practice plan ' +
      'targeting those corners. During the weekend, upload each session immediately ' +
      'and compare with your target reference lap. After each run, check whether ' +
      'your worst corners improved. This structured approach replaces seat-of-the-' +
      'pants "just drive more laps" with measurable iteration.',
  },
  {
    question: 'How do I develop a race strategy?',
    answer:
      'Race strategy starts with understanding your pace window — what is your ' +
      'realistic consistent lap time? The consistency pillar in Lap Coach tells you ' +
      'whether your average is close to your best. If sigma is high, focus on ' +
      'repeatable pace before worrying about outright speed. Then use the stint ' +
      'analysis chart to see how your pace degrades over a stint — this tells you ' +
      'whether you can push early or need to save tyres.',
  },
  {
    question: 'How do I debrief after a race session?',
    answer:
      'A structured debrief follows three steps: (1) review the four-pillar score — ' +
      'which pillar dropped? (2) open the time-delta chart and identify the three ' +
      'biggest climbs — those are where you lost the most time; (3) for each of those ' +
      'climbs, open the corner coaching view and read the entry/apex/exit breakdown. ' +
      'Write down one thing to fix per corner. Limit your next run to practising ' +
      'those specific corners. Upload again and check the delta.',
  },
  {
    question: 'How do I manage tire wear during a race?',
    answer:
      'Tire degradation shows up as a rising lap time over a stint. The lap progress ' +
      'chart in Lap Coach shows this trend. If your times climb steeply after lap 5, ' +
      'you may be overdriving early. Smooth inputs — gentler braking, progressive ' +
      'throttle — reduce thermal cycling. When tire temp data is available (from CAN ' +
      'loggers), the tire heatmap chart shows which corners are overheating which ' +
      'tires, so you know where to reduce attack.',
  },

  // ── Data logging / hardware ───────────────────────────────────
  {
    question: 'What GPS data logger should I buy for track days?',
    answer:
      'For most club-level drivers, a phone running RaceChrono Pro (with an external ' +
      'Bluetooth GPS for 10 Hz) is the best starting point — inexpensive and exports ' +
      'CSVs that work with Lap Coach. RaceBox Micro gives standalone 25 Hz GPS with ' +
      'no phone needed. For more channels (throttle, brake, RPM), an AiM Solo 2 DL ' +
      'or MoTeC C125 adds OBD-II or CAN integration. Start simple — GPS-only is ' +
      'enough to find most of your time.',
  },
  {
    question: 'How do I set up data logging for my car?',
    answer:
      'Mount a GPS logger (phone with RaceChrono, RaceBox, or standalone unit) with ' +
      'clear sky view — on the dash or roll bar, not behind a windshield if possible. ' +
      'Start recording before you leave pit lane. After the session, export the CSV. ' +
      'Upload it to your analysis tool. If you want throttle/brake/RPM data, connect ' +
      'an OBD-II adapter (Bluetooth or CAN) to your logger — most modern loggers ' +
      'support this. For karts, GPS-only is the norm since there is no OBD.',
  },
  {
    question: 'How do I set up RaceChrono for karting?',
    answer:
      'Install RaceChrono Pro, pair a 10 Hz external Bluetooth GPS (the Qstarz ' +
      'BL-818GT or RaceBox Mini are popular). Mount the phone where it can see sky. ' +
      'In RaceChrono, set the track or let it auto-detect. Start recording before ' +
      'going on track. After the session, export as CSV and upload to Lap Coach for ' +
      'corner detection, scoring, and coaching insights. No CAN setup needed for karts.',
  },
  {
    question: 'What is the difference between data logging and telemetry?',
    answer:
      'Data logging = recording sensor data (speed, GPS, throttle, etc.) to a file ' +
      'for later analysis. Telemetry = real-time or near-real-time transmission of ' +
      'that data to a pit crew or engineer. In club racing, most drivers do data ' +
      'logging (record → export → analyse after the session). Professional teams ' +
      'do live telemetry (stream data to the pit wall during the race). Lap Coach ' +
      'is a post-session analysis tool: it reads logged data, not live streams.',
  },
  {
    question: 'How do I set up a dash logger or data display?',
    answer:
      'AiM Solo 2, AiM MXS, and MoTeC C125 are popular options. Mount it in your ' +
      'line of sight. Connect power (12 V from the car), connect the GPS antenna, ' +
      'and optionally wire CAN or OBD-II for engine data. Configure the channels ' +
      'you want (RPM, throttle position, coolant temp) via the manufacturer software. ' +
      'After the session, export the data as CSV and upload to your analysis tool.',
  },

  // ── Real-life telemetry analysis ──────────────────────────────
  {
    question: 'What data should I look at after a track day?',
    answer:
      'Start with the delta chart: where did you gain and lose time vs your best lap? ' +
      'Then look at the corner coaching table to identify the three worst corners. For ' +
      'each, check: did you brake too early (entry speed)? Carry too little minimum ' +
      'speed (apex)? Get on throttle too late or too abruptly (exit)? The G-G diagram ' +
      'tells you whether you used the available grip. Do NOT try to fix everything at ' +
      'once — pick one corner per run.',
  },
  {
    question: 'How do I read a speed trace chart?',
    answer:
      'X-axis = distance around the lap (metres). Y-axis = speed (km/h or mph). ' +
      'Valleys = braking zones and corners. Peaks = straights. Compare two laps by ' +
      'overlaying their speed traces: where the faster lap is higher, you carried ' +
      'more speed. Where it is lower, you braked later. The delta chart below the ' +
      'speed trace integrates these differences into a cumulative time-gained/lost ' +
      'curve.',
  },
  {
    question: 'How do I analyse braking data from telemetry?',
    answer:
      'Look at the brake trace vs distance: a steep ramp-up = hard initial braking ' +
      '(good). A long gradual ramp = "squeezing" the brake (slow). The brake point ' +
      'distance should be consistent lap-to-lap — if it varies by 10+ metres you are ' +
      'guessing, not driving. Brake release should taper smoothly into the corner ' +
      '(trail braking). If the trace drops to zero before turn-in, you are coasting. ' +
      'If it spikes at apex, you braked too late.',
  },
  {
    question: 'How do I analyse sector times?',
    answer:
      'Split the lap into sectors (by distance or by corner group). For each sector, ' +
      'compare your time to your best-ever sector and to the theoretical. If sector 2 ' +
      'is consistently your worst, that is where to focus practice. Lap Coach shows ' +
      'sector splits with per-sector delta bars — green means you matched or beat ' +
      'your best, red means you lost time there.',
  },
  {
    question: 'How do I use telemetry for driver coaching?',
    answer:
      'A coach reviews the data WITH the driver: open the session, identify the ' +
      'three worst corners, and show the driver exactly what happened using the ' +
      'speed trace, track map, and delta chart. Then have the driver explain what ' +
      'they felt. Compare their perception to the data. This reality check is the ' +
      'biggest value of telemetry coaching. Lap Coach generates PDF reports ' +
      'specifically for this debrief workflow.',
  },
  {
    question: 'How much faster can I realistically get?',
    answer:
      'The theoretical perfect lap in Lap Coach gives a physics-based upper bound. ' +
      'Most club drivers are 3–8% off the theoretical. Each pillar of the four-pillar ' +
      'score tells you WHERE that gap lives. If your pace is high but consistency is ' +
      'low, the gains are in repeating what you already know how to do. If execution ' +
      'is low, the gains are in specific corners. If you are within 1–2% of ' +
      'theoretical, you are approaching diminishing returns and should look at setup.',
  },
  {
    question: 'How do I compare my driving to a faster driver?',
    answer:
      'Both drivers record the same track with the same logger format. Upload both ' +
      'sessions. Use the cross-session reference overlay to pick the faster driver ' +
      'as the reference lap. Every chart now shows both drivers side by side — ' +
      'speed trace, GPS line, G-G envelope, and the delta chart shows exactly where ' +
      'the faster driver pulls away. Focus on the biggest delta climb — that is the ' +
      'corner or section where you are leaving the most time.',
  },
  {
    question: 'How do I track driving improvement over time?',
    answer:
      'Upload every session on the same track. The session comparison chart shows ' +
      'your best-lap trend over time. The four-pillar scores track whether your ' +
      'pace, consistency, execution, and robustness are improving. Cross-session ' +
      'reference overlays let you compare this month vs last month on the same ' +
      'corner to see concrete gains. Track your theoretical gap — it should shrink ' +
      'over time as you clean up technique.',
  },

  // ── Sim racing telemetry ──────────────────────────────────────
  {
    question: 'How do I use telemetry in iRacing?',
    answer:
      'iRacing generates .ibt telemetry files. Export them to CSV using the iRacing ' +
      'telemetry viewer or a third-party tool. Upload the CSV to Lap Coach for ' +
      'corner detection, scoring, and delta analysis. Sim telemetry is especially ' +
      'useful for learning a new track before a real-world event — the corners and ' +
      'reference points transfer directly.',
  },
  {
    question: 'How do I use telemetry in Assetto Corsa Competizione?',
    answer:
      'ACC logs telemetry in its own format. Use MoTeC i2 Pro (bundled free with ' +
      'ACC) to open the data and export as CSV. Upload the CSV to Lap Coach for ' +
      'the same analysis you would run on real-world data: corner coaching, delta ' +
      'charts, G-G diagrams, and four-pillar scoring. This lets you practise the ' +
      'debrief workflow before you get to a real track.',
  },
  {
    question: 'How do I transfer sim racing skills to a real car?',
    answer:
      'The biggest transfer is cornering references — brake points, turn-in points, ' +
      'and apex targets. Sim telemetry helps you learn these before the real event. ' +
      'What does NOT transfer well: absolute speed, brake pedal feel, and tire ' +
      'feedback. Use sim sessions to learn the SHAPE of each corner (when to brake, ' +
      'when to turn, when to throttle) and use real-world sessions to calibrate the ' +
      'INTENSITY of each input. Compare both sessions in Lap Coach to see how your ' +
      'real-world execution compares to your sim reference.',
  },
  {
    question: 'Can I use sim racing telemetry to improve in real life?',
    answer:
      'Yes, for track learning and debrief practice. Upload your sim session, review ' +
      'the speed trace and corner coaching, build a plan. Then upload your first ' +
      'real-world session on the same track and compare the two. The delta chart ' +
      'shows exactly where reality diverged from the sim. Corner-by-corner, you ' +
      'will see which habits transferred and which need adjustment.',
  },
  {
    question: 'Best free telemetry analysis tools for racing?',
    answer:
      'Lap Coach offers two free reports with no credit card. RaceChrono Pro has ' +
      'basic built-in analysis (speed trace, GPS map). MoTeC i2 Pro is free with ' +
      'ACC/iRacing data. Harry\'s Lap Timer has a basic analysis view. For serious ' +
      'analysis beyond basic overlays — per-corner coaching, four-pillar scoring, ' +
      'theoretical perfect-lap comparison — Lap Coach is the most driver-friendly ' +
      'option at €69/year.',
  },

  // ── Conditions & edge cases ───────────────────────────────────
  {
    question: 'How do I use telemetry in wet or changing conditions?',
    answer:
      'Wet driving changes everything — brake points move earlier, corner speeds ' +
      'drop, and the racing line shifts to avoid standing water. Upload the wet ' +
      'session and compare it to a dry reference. The delta chart shows where the ' +
      'wet lap lost the most time — those are the corners that are most grip-' +
      'limited in the wet. Focus on smooth inputs and consistent lines rather than ' +
      'chasing dry-condition speed. The robustness pillar in Lap Coach specifically ' +
      'measures how well you adapt to changing conditions.',
  },
  {
    question: 'How do I warm up tires on track?',
    answer:
      'Tire warm-up shows in telemetry as rising corner speeds over the first 1–3 ' +
      'laps. If you push too hard on cold tires you will see understeer (wide lines ' +
      'on the GPS map) and lower lateral G on the G-G diagram. Build speed gradually: ' +
      '70% on lap 1, 85% on lap 2, 100% on lap 3. The lap progress chart in Lap ' +
      'Coach shows this ramp — your times should decrease steadily over the first ' +
      'three laps. If they plateau on lap 1, your tires were already warm or you ' +
      'are not building pressure properly.',
  },
];

function Divider() {
  return <div className="section-divider" aria-hidden="true" />;
}

export default function Home() {
  return (
    <main id="main-content">
      <JsonLd
        pathname="/"
        softwareApp
        organization
        howTo={HOWTO_FASTER_LAPS}
        faqItems={HOMEPAGE_FAQ}
      />
      <h1 className="sr-only">
        LAP Coach — Motorsport telemetry analysis for kart and car drivers
      </h1>
      <StartGrid />
      <Divider />
      <SessionProof />
      <Divider />
      <S1Pain />
      <Divider />
      <S2Versus />
      <S3Product />
      <Divider />
      <SimFirst />
      <Divider />
      <PremiumLayer />
      <Divider />
      <Garage />
      <Divider />
      <PitStop />
      <Divider />
      <Podium />
    </main>
  );
}
