import { motion, AnimatePresence } from "motion/react";
import { Star } from "lucide-react";

interface FloatingPoint {
  id: string;
  points: number;
  x: number;
  y: number;
}

interface PointsAnimationProps {
  floatingPoints: FloatingPoint[];
}

export function PointsAnimation({ floatingPoints }: PointsAnimationProps) {
  return (
    <div className="fixed inset-0 pointer-events-none z-50">
      <AnimatePresence>
        {floatingPoints.map((point) => (
          <motion.div
            key={point.id}
            initial={{ opacity: 1, y: 0, x: point.x, scale: 1 }}
            animate={{ opacity: 0, y: -100, scale: 1.5 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 1.5, ease: "easeOut" }}
            className="absolute flex items-center gap-1 font-bold text-yellow-500 text-2xl"
            style={{ left: point.x, top: point.y }}
          >
            <Star className="h-6 w-6 fill-yellow-500" />
            +{point.points}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
