# Core Image imports (macOS only)


class CoreImageBackend(ImageBackend):
    """Core Image backend for Apple Silicon GPU acceleration."""

    def __init__(self):
        if not CORE_IMAGE_AVAILABLE:
            raise ImportError(
                "Core Image not available. This backend requires macOS with pyobjc."
            )

        # Create GPU-accelerated Core Image context
        self.context = CIContext.contextWithOptions_(
            {
                # Use GPU acceleration
                "kCIContextUseSoftwareRenderer": False,
                # Use wide color gamut
                kCIContextWorkingColorSpace: CGColorSpaceCreateDeviceRGB(),
            }
        )

    def process_image_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        # Load image using Core Image
        file_url = NSURL.fileURLWithPath_(file_path)
        ci_image = CIImage.imageWithContentsOfURL_(file_url)

        if ci_image is None:
            raise ValueError(f"Could not load image from {file_path}")

        return self._process_ci_image(ci_image, sizes, output_format, quality)

    def process_image_bytes(
        self,
        image_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        # Convert bytes to NSData
        ns_data = NSData.dataWithBytes_length_(image_bytes, len(image_bytes))
        ci_image = CIImage.imageWithData_(ns_data)

        if ci_image is None:
            raise ValueError("Could not create CIImage from bytes")

        return self._process_ci_image(ci_image, sizes, output_format, quality)

    def process_pil_image(
        self,
        pil_image: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        # Convert PIL image to bytes, then to Core Image
        buffer = io.BytesIO()

        # Ensure RGB mode for consistency
        if pil_image.mode not in ("RGB", "RGBA"):
            pil_image = pil_image.convert("RGB")

        # Auto-orient based on EXIF
        pil_image = ImageOps.exif_transpose(pil_image)

        # Save as PNG to preserve quality during conversion
        pil_image.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        return self.process_image_bytes(image_bytes, sizes, output_format, quality)

    def _process_ci_image(
        self,
        ci_image: "CIImage",
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        results = {}

        # Get original image dimensions
        extent = ci_image.extent()
        original_width = extent.size.width
        original_height = extent.size.height

        # Sort sizes by area (largest first) for optimal processing
        sorted_sizes = sorted(
            sizes.items(), key=lambda x: x[1][0] * x[1][1], reverse=True
        )

        for size_name, (target_width, target_height) in sorted_sizes:
            # Calculate scale factor to fit within target size (maintaining aspect ratio)
            scale_x = target_width / original_width
            scale_y = target_height / original_height
            scale = min(scale_x, scale_y)

            # Apply GPU-accelerated scaling using Lanczos algorithm
            scale_filter = CIFilter.filterWithName_("CILanczosScaleTransform")
            scale_filter.setValue_forKey_(ci_image, "inputImage")
            scale_filter.setValue_forKey_(scale, "inputScale")
            scale_filter.setValue_forKey_(
                1.0, "inputAspectRatio"
            )  # Maintain aspect ratio

            scaled_image = scale_filter.outputImage()

            # Render to bytes
            image_bytes = self._render_to_bytes(scaled_image, output_format, quality)
            results[size_name] = image_bytes

        return results

    def _render_to_bytes(
        self, ci_image: "CIImage", output_format: str, quality: int
    ) -> bytes:
        """Render CIImage to bytes in specified format."""
        # Get image extent
        extent = ci_image.extent()

        # Render to CGImage
        cg_image = self.context.createCGImage_fromRect_(ci_image, extent)

        if cg_image is None:
            raise RuntimeError("Failed to create CGImage from CIImage")

        # Determine UTI type
        if output_format.upper() == "JPEG":
            uti_type = UTType.typeWithIdentifier_("public.jpeg")
        elif output_format.upper() == "PNG":
            uti_type = UTType.typeWithIdentifier_("public.png")
        elif output_format.upper() == "WEBP":
            uti_type = UTType.typeWithIdentifier_("org.webmproject.webp")
        else:
            raise ValueError(f"Unsupported output format: {output_format}")

        # Create mutable data for output
        output_data = NSData.data().mutableCopy()

        # Create image destination
        destination = CGImageDestinationCreateWithData(
            output_data, uti_type.identifier(), 1, None  # image count
        )

        if destination is None:
            raise RuntimeError(
                f"Failed to create image destination for {output_format}"
            )

        # Set properties
        properties = {}
        if output_format.upper() == "JPEG":
            properties[kCGImageDestinationLossyCompressionQuality] = quality / 100.0

        # Add image to destination
        CGImageDestinationAddImage(destination, cg_image, properties)

        # Finalize
        if not CGImageDestinationFinalize(destination):
            raise RuntimeError("Failed to finalize image destination")

        # Convert NSData to Python bytes
        return bytes(output_data)
