"use client";

import { motion } from "framer-motion";

export function ProgressLine({ text }: { text: string }) {
  return (
    <div className="flex items-baseline gap-1 text-sm text-muted-foreground">
      <span>{text}</span>
      <span className="inline-flex" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="mx-px"
            animate={{ opacity: [0.2, 1, 0.2] }}
            transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.2 }}
          >
            .
          </motion.span>
        ))}
      </span>
    </div>
  );
}
