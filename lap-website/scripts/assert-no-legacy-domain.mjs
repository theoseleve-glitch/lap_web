import { readFileSync } from 'node:fs';

const filesToCheck = [
  'src/lib/site-url.ts',
  'src/app/layout.tsx',
  'src/app/sitemap.ts',
  'src/app/robots.ts',
  'src/app/api/billing/checkout/route.ts',
];

const forbiddenLiteral = 'lap.racing';
const offenders = [];

for (const file of filesToCheck) {
  const contents = readFileSync(file, 'utf8');
  if (contents.includes(forbiddenLiteral)) {
    offenders.push(file);
  }
}

if (offenders.length > 0) {
  console.error(`Found forbidden domain literal "${forbiddenLiteral}" in:`);
  for (const file of offenders) {
    console.error(`- ${file}`);
  }
  process.exit(1);
}

console.log(`No forbidden domain literals found in ${filesToCheck.length} production config files.`);
