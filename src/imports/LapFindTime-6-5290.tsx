import clsx from "clsx";
type ContainerBackgroundImageProps = {
  additionalClassNames?: string;
};

function ContainerBackgroundImage({ children, additionalClassNames = "" }: React.PropsWithChildren<ContainerBackgroundImageProps>) {
  return (
    <div className={clsx("relative shrink-0", additionalClassNames)}>
      <div className="bg-clip-padding border-0 border-[transparent] border-solid relative size-full">{children}</div>
    </div>
  );
}

export default function LapFindTime() {
  return (
    <div className="bg-black content-stretch flex flex-col items-start relative size-full" data-name="LAP — Find Time.">
      <div className="bg-black h-[593px] overflow-clip relative shrink-0 w-full" data-name="Main Content">
        <div className="absolute h-[593px] left-0 top-0 w-[1280px]" data-name="Container" style={{ backgroundImage: "url('data:image/svg+xml;utf8,<svg viewBox=\\'0 0 1280 593\\' xmlns=\\'http://www.w3.org/2000/svg\\' preserveAspectRatio=\\'none\\'><rect x=\\'0\\' y=\\'0\\' height=\\'100%\\' width=\\'100%\\' fill=\\'url(%23grad)\\' opacity=\\'1\\'/><defs><radialGradient id=\\'grad\\' gradientUnits=\\'userSpaceOnUse\\' cx=\\'0\\' cy=\\'0\\' r=\\'10\\' gradientTransform=\\'matrix(0 -87.25 -87.25 0 640 0)\\'><stop stop-color=\\'rgba(182,255,46,0.16)\\' offset=\\'0\\'/><stop stop-color=\\'rgba(91,128,23,0.08)\\' offset=\\'0.13\\'/><stop stop-color=\\'rgba(0,0,0,0)\\' offset=\\'0.26\\'/></radialGradient></defs></svg>'), linear-gradient(rgb(5, 5, 5) 0%, rgb(10, 10, 10) 45%, rgb(0, 0, 0) 100%)" }} />
        <div className="absolute h-[593px] left-[64px] top-0 w-[1152px]" data-name="Container">
          <div className="absolute bg-[rgba(255,255,255,0.03)] border border-[rgba(255,255,255,0.1)] border-solid h-[86px] left-[40px] rounded-[28px] top-[40px] w-[1072px]" data-name="Container">
            <div className="absolute content-stretch flex flex-col gap-[8px] h-[41.594px] items-start left-[24px] top-[21.2px] w-[313.682px]" data-name="Container">
              <div className="h-[13.198px] relative shrink-0 w-full" data-name="Paragraph">
                <p className="absolute font-['Space_Mono:Regular',sans-serif] leading-[13.2px] left-0 not-italic text-[#f0ede5] text-[11px] top-[-0.67px] tracking-[1.32px] uppercase whitespace-nowrap">Reward State</p>
              </div>
              <div className="h-[20.396px] relative shrink-0 w-full" data-name="Heading 1">
                <p className="absolute font-['Space_Grotesk:Bold',sans-serif] font-bold leading-[20.4px] left-0 text-[#f0ede5] text-[24px] top-[-0.33px] tracking-[-0.48px] uppercase whitespace-nowrap">Level-Up Modal And Toast</p>
              </div>
            </div>
            <div className="absolute content-stretch flex h-[44px] items-center left-[893.27px] px-[17px] py-[9px] rounded-[9999px] top-[20px] w-[152.734px]" data-name="Link">
              <div aria-hidden="true" className="absolute border border-[rgba(255,255,255,0.15)] border-solid inset-0 pointer-events-none rounded-[9999px]" />
              <p className="font-['Inter:Regular',sans-serif] font-normal leading-[24.08px] not-italic relative shrink-0 text-[#f0ede5] text-[14px] whitespace-nowrap">Back to catalogue</p>
            </div>
          </div>
          <div className="absolute bg-gradient-to-b border border-[rgba(255,255,255,0.1)] border-solid from-[rgba(15,15,15,0.92)] h-[395px] left-[40px] overflow-clip rounded-[32px] shadow-[0px_40px_120px_-64px_rgba(182,255,46,0.4)] to-[rgba(6,6,6,0.98)] top-[158px] w-[1072px]" data-name="Container">
            <div className="absolute h-[393px] left-0 top-0 w-[1070px]" data-name="Container" style={{ backgroundImage: "url('data:image/svg+xml;utf8,<svg viewBox=\\'0 0 1070 393\\' xmlns=\\'http://www.w3.org/2000/svg\\' preserveAspectRatio=\\'none\\'><rect x=\\'0\\' y=\\'0\\' height=\\'100%\\' width=\\'100%\\' fill=\\'url(%23grad)\\' opacity=\\'1\\'/><defs><radialGradient id=\\'grad\\' gradientUnits=\\'userSpaceOnUse\\' cx=\\'0\\' cy=\\'0\\' r=\\'10\\' gradientTransform=\\'matrix(0 -58.466 -58.466 0 535 157.2)\\'><stop stop-color=\\'rgba(34,197,94,0.09)\\' offset=\\'0\\'/><stop stop-color=\\'rgba(0,0,0,0)\\' offset=\\'0.28\\'/></radialGradient></defs></svg>'), url('data:image/svg+xml;utf8,<svg viewBox=\\'0 0 1070 393\\' xmlns=\\'http://www.w3.org/2000/svg\\' preserveAspectRatio=\\'none\\'><rect x=\\'0\\' y=\\'0\\' height=\\'100%\\' width=\\'100%\\' fill=\\'url(%23grad)\\' opacity=\\'1\\'/><defs><radialGradient id=\\'grad\\' gradientUnits=\\'userSpaceOnUse\\' cx=\\'0\\' cy=\\'0\\' r=\\'10\\' gradientTransform=\\'matrix(0 -93.745 -93.745 0 877.4 62.88)\\'><stop stop-color=\\'rgba(255,212,0,0.08)\\' offset=\\'0\\'/><stop stop-color=\\'rgba(0,0,0,0)\\' offset=\\'0.2\\'/></radialGradient></defs></svg>')" }} />
            <div className="absolute bg-[rgba(0,0,0,0.55)] h-[393px] left-0 top-0 w-[1070px]" data-name="Container" />
            <div className="absolute bg-[#141414] content-stretch flex flex-col h-[111.365px] items-start left-[646px] pb-[2px] pt-[18px] px-[18px] rounded-[16px] top-[40px] w-[384px]" data-name="Container">
              <div aria-hidden="true" className="absolute border-2 border-[#c9a84c] border-solid inset-0 pointer-events-none rounded-[16px] shadow-[0px_20px_48px_0px_rgba(201,168,76,0.45)]" />
              <div className="content-stretch flex gap-[12px] h-[75.365px] items-start relative shrink-0 w-full" data-name="Container">
                <ContainerBackgroundImage additionalClassNames="h-[36px] w-[39.099px]">
                  <p className="absolute font-['Inter:Regular',sans-serif] font-normal leading-[36px] left-0 not-italic text-[#f0ede5] text-[30px] top-[-0.33px] whitespace-nowrap">⚡</p>
                </ContainerBackgroundImage>
                <div className="flex-[273.651_0_0] h-[75.365px] min-h-px min-w-px relative" data-name="Container">
                  <div className="bg-clip-padding border-0 border-[transparent] border-solid relative size-full">
                    <div className="absolute h-[10.198px] left-0 top-0 w-[273.651px]" data-name="Paragraph">
                      <p className="absolute font-['Space_Grotesk:Bold',sans-serif] font-bold leading-[10.2px] left-0 text-[#c9a84c] text-[12px] top-[0.33px] tracking-[-0.24px] uppercase whitespace-nowrap">Achievement Unlocked</p>
                    </div>
                    <div className="absolute h-[11.896px] left-0 top-[14.2px] w-[273.651px]" data-name="Paragraph">
                      <p className="absolute font-['Space_Grotesk:Bold',sans-serif] font-bold leading-[11.9px] left-0 text-[#f0ede5] text-[14px] top-0 tracking-[-0.28px] uppercase whitespace-nowrap">Precision Attack</p>
                    </div>
                    <div className="absolute h-[41.271px] left-0 top-[34.09px] w-[273.651px]" data-name="Paragraph">
                      <p className="absolute font-['Inter:Regular',sans-serif] font-normal leading-[20.64px] left-0 not-italic text-[#949494] text-[12px] top-[-0.33px] w-[266px]">Three execution gains in a row without a single invalid lap.</p>
                    </div>
                  </div>
                </div>
                <ContainerBackgroundImage additionalClassNames="h-[29.24px] w-[11.25px]">
                  <p className="absolute font-['Inter:Regular',sans-serif] font-normal leading-[29.24px] left-0 not-italic text-[#949494] text-[17px] top-[0.33px] whitespace-nowrap">×</p>
                </ContainerBackgroundImage>
              </div>
            </div>
            <div className="absolute bg-[#141414] border-2 border-[#22c55e] border-solid h-[298.698px] left-[311px] rounded-[28px] shadow-[0px_30px_90px_0px_rgba(34,197,94,0.45)] top-[47.15px] w-[448px]" data-name="Container">
              <div className="absolute h-[25.5px] left-[32px] top-[32px] w-[380px]" data-name="Paragraph">
                <p className="-translate-x-1/2 absolute font-['Space_Grotesk:Bold',sans-serif] font-bold leading-[25.5px] left-[189.58px] text-[#22c55e] text-[30px] text-center top-[-0.67px] tracking-[-0.6px] uppercase whitespace-nowrap">LEVEL UP!</p>
              </div>
              <div className="absolute content-stretch flex gap-[16px] h-[64px] items-center justify-center left-[32px] px-[99.646px] top-[89.5px] w-[380px]" data-name="Container">
                <div className="relative rounded-[9999px] shrink-0 size-[64px]" data-name="Container">
                  <div aria-hidden="true" className="absolute border-2 border-[#949494] border-solid inset-0 pointer-events-none rounded-[9999px]" />
                  <div className="bg-clip-padding border-0 border-[transparent] border-solid content-stretch flex items-center justify-center p-[2px] relative size-full">
                    <p className="font-['Space_Grotesk:Bold',sans-serif] font-bold leading-[20.4px] relative shrink-0 text-[#949494] text-[24px] text-center tracking-[-0.48px] uppercase whitespace-nowrap">5</p>
                  </div>
                </div>
                <ContainerBackgroundImage additionalClassNames="h-[32px] w-[20.708px]">
                  <p className="-translate-x-1/2 absolute font-['Inter:Regular',sans-serif] font-normal leading-[32px] left-[10.5px] not-italic text-[#949494] text-[24px] text-center top-[-0.67px] whitespace-nowrap">→</p>
                </ContainerBackgroundImage>
                <div className="bg-[rgba(34,197,94,0.15)] relative rounded-[9999px] shrink-0 size-[64px]" data-name="Container">
                  <div aria-hidden="true" className="absolute border-2 border-[#22c55e] border-solid inset-0 pointer-events-none rounded-[9999px] shadow-[0px_0px_32px_0px_rgba(34,197,94,0.25)]" />
                  <div className="bg-clip-padding border-0 border-[transparent] border-solid content-stretch flex items-center justify-center p-[2px] relative size-full">
                    <p className="font-['Space_Grotesk:Bold',sans-serif] font-bold leading-[20.4px] relative shrink-0 text-[#22c55e] text-[24px] text-center tracking-[-0.48px] uppercase whitespace-nowrap">6</p>
                  </div>
                </div>
              </div>
              <div className="absolute h-[13.198px] left-[32px] top-[177.5px] w-[380px]" data-name="Paragraph">
                <p className="-translate-x-1/2 absolute font-['Space_Mono:Regular',sans-serif] leading-[0] left-[189.61px] not-italic text-[#949494] text-[11px] text-center top-[-0.67px] tracking-[1.32px] uppercase whitespace-nowrap">
                  <span className="leading-[13.2px]">{`Total XP: `}</span>
                  <span className="leading-[13.2px] text-[#f0ede5]">1,640</span>
                </p>
              </div>
              <div className="absolute bg-[#22c55e] h-[44px] left-[161.95px] rounded-[12px] top-[218.7px] w-[120.094px]" data-name="Button">
                <p className="-translate-x-1/2 absolute font-['Space_Grotesk:Bold',sans-serif] font-bold leading-[11.9px] left-[60.5px] text-[14px] text-black text-center top-[16.05px] tracking-[-0.28px] uppercase whitespace-nowrap">Continue</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}